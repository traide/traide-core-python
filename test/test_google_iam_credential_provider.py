import asyncio
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import pytest
from google.auth.exceptions import RefreshError

from traide.redis.google_iam_credential_provider import GoogleIamCredentialProvider

START = datetime(2026, 10, 26, 12, 0, 0)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


class StubCredentials:
    def __init__(self, clock: Clock, refresh_duration_seconds: float = 0) -> None:
        self._clock = clock
        self._refresh_duration_seconds = refresh_duration_seconds
        self.token: str | None = None
        self.expiry: datetime | None = None
        self.refresh_count = 0
        self.fail_next_refresh = False
        self.refresh_thread: threading.Thread | None = None

    def refresh(self, request: Any) -> None:
        self.refresh_thread = threading.current_thread()
        time.sleep(self._refresh_duration_seconds)
        if self.fail_next_refresh:
            self.fail_next_refresh = False
            raise RefreshError("refresh failed")
        self.refresh_count += 1
        self.token = f"token-{self.refresh_count}"
        self.expiry = self._clock() + timedelta(hours=1)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def credentials(clock: Clock) -> StubCredentials:
    return StubCredentials(clock=clock)


@pytest.fixture
def loader_calls() -> list[None]:
    return []


@pytest.fixture
def provider(credentials: StubCredentials, clock: Clock, loader_calls: list[None]) -> GoogleIamCredentialProvider:
    return _provider(credentials=credentials, clock=clock, loader_calls=loader_calls)


def _provider(credentials: StubCredentials, clock: Clock, loader_calls: list[None]) -> GoogleIamCredentialProvider:
    def load() -> StubCredentials:
        loader_calls.append(None)
        return credentials

    return GoogleIamCredentialProvider(credentials_loader=load, clock=clock)


def _expiry(credentials: StubCredentials) -> datetime:
    assert credentials.expiry is not None
    return credentials.expiry


def test_first_call_refreshes_and_returns_the_default_username_with_the_token(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    assert provider.get_credentials() == ("default", "token-1")
    assert credentials.refresh_count == 1


def test_reuses_the_token_while_more_than_five_minutes_remain(provider: GoogleIamCredentialProvider, credentials: StubCredentials, clock: Clock) -> None:
    provider.get_credentials()
    clock.now = _expiry(credentials) - timedelta(minutes=6)
    assert provider.get_credentials() == ("default", "token-1")


def test_refreshes_the_token_when_less_than_five_minutes_remain(provider: GoogleIamCredentialProvider, credentials: StubCredentials, clock: Clock) -> None:
    provider.get_credentials()
    clock.now = _expiry(credentials) - timedelta(minutes=4)
    assert provider.get_credentials() == ("default", "token-2")


def test_loads_credentials_once(provider: GoogleIamCredentialProvider, loader_calls: list[None]) -> None:
    for _ in range(3):
        provider.get_credentials()
    assert len(loader_calls) == 1


def test_loads_nothing_until_credentials_are_requested(provider: GoogleIamCredentialProvider, loader_calls: list[None]) -> None:
    assert loader_calls == []


def test_keeps_the_cached_token_when_a_refresh_fails_before_expiry(provider: GoogleIamCredentialProvider, credentials: StubCredentials, clock: Clock) -> None:
    provider.get_credentials()
    clock.now = _expiry(credentials) - timedelta(minutes=4)
    credentials.fail_next_refresh = True
    assert provider.get_credentials() == ("default", "token-1")


def test_raises_when_a_refresh_fails_after_expiry(provider: GoogleIamCredentialProvider, credentials: StubCredentials, clock: Clock) -> None:
    provider.get_credentials()
    clock.now = _expiry(credentials) + timedelta(seconds=1)
    credentials.fail_next_refresh = True
    with pytest.raises(RefreshError):
        provider.get_credentials()


def test_concurrent_callers_share_one_refresh(clock: Clock) -> None:
    slow_credentials = StubCredentials(clock=clock, refresh_duration_seconds=0.2)
    provider = _provider(credentials=slow_credentials, clock=clock, loader_calls=[])
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
