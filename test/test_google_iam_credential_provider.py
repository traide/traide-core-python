import asyncio
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from google.auth.credentials import Credentials, TokenState
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from redis.exceptions import AuthenticationError
from structlog.testing import capture_logs

from traide.redis import google_iam_credential_provider as provider_module
from traide.redis.google_iam_credential_provider import REFRESH_RETRY_DELAY, REFRESH_TIMEOUT_SECONDS, GoogleIamCredentialProvider

GOOGLE_AUTH_REFRESH_THRESHOLD = timedelta(minutes=3, seconds=45)
STALE_LIFETIME = timedelta(minutes=2)
WITHIN_SAFETY_MARGIN = timedelta(seconds=20)
THREAD_TIMEOUT_SECONDS = 5


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class StubCredentials:
    def __init__(self) -> None:
        self.token: str | None = None
        self.expiry: datetime | None = None
        self.refresh_count = 0
        self.attempt_count = 0
        self.fail_next_refresh = False
        self.issue_empty_token = False
        self.refresh_entered = threading.Event()
        self.refresh_may_finish = threading.Event()
        self.refresh_may_finish.set()
        self.refresh_thread: threading.Thread | None = None
        self.requests: list[Any] = []

    @property
    def token_state(self) -> TokenState:
        if self.token is None:
            return TokenState.INVALID
        if self.expiry is None:
            return TokenState.FRESH
        if _now() >= self.expiry:
            return TokenState.INVALID
        if _now() >= self.expiry - GOOGLE_AUTH_REFRESH_THRESHOLD:
            return TokenState.STALE
        return TokenState.FRESH

    def refresh(self, request: Any) -> None:
        self.refresh_thread = threading.current_thread()
        self.requests.append(request)
        self.attempt_count += 1
        self.refresh_entered.set()
        self.refresh_may_finish.wait(THREAD_TIMEOUT_SECONDS)
        if self.fail_next_refresh:
            self.fail_next_refresh = False
            raise RefreshError("refresh failed")
        if self.issue_empty_token:
            return
        self.refresh_count += 1
        self.token = f"token-{self.refresh_count}"
        self.expiry = _now() + timedelta(hours=1)

    def expire_in(self, remaining: timedelta) -> None:
        self.expiry = _now() + remaining


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
    def load() -> Credentials:
        loader_calls.append(None)
        return cast(Credentials, credentials)

    return GoogleIamCredentialProvider(credentials_loader=load)


def _hold_off_refreshes(provider: GoogleIamCredentialProvider) -> None:
    provider._retry_not_before = _now() + REFRESH_RETRY_DELAY  # pyright: ignore[reportPrivateUsage]


def _refresh_held_off(provider: GoogleIamCredentialProvider) -> bool:
    retry_not_before = provider._retry_not_before  # pyright: ignore[reportPrivateUsage]
    return retry_not_before is not None and retry_not_before > _now()


def _start_blocked_refresh(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> threading.Thread:
    credentials.refresh_entered.clear()
    credentials.refresh_may_finish.clear()
    refresher = threading.Thread(target=provider.get_credentials)
    refresher.start()
    assert credentials.refresh_entered.wait(THREAD_TIMEOUT_SECONDS)
    return refresher


def _start_callers(provider: GoogleIamCredentialProvider, count: int) -> tuple[list[tuple[str, str]], list[threading.Thread]]:
    results: list[tuple[str, str]] = []
    threads = [threading.Thread(target=lambda: results.append(provider.get_credentials())) for _ in range(count)]
    for thread in threads:
        thread.start()
    return results, threads


def _join(threads: list[threading.Thread], timeout_seconds: float = THREAD_TIMEOUT_SECONDS) -> bool:
    for thread in threads:
        thread.join(timeout_seconds)
    return not any(thread.is_alive() for thread in threads)


def _forbid_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("asyncio.to_thread was used")

    monkeypatch.setattr(provider_module.asyncio, "to_thread", fail)


def test_first_call_refreshes_and_returns_the_default_username_with_the_token(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    assert provider.get_credentials() == ("default", "token-1")
    assert credentials.refresh_count == 1


def test_a_fresh_token_is_returned_without_a_refresh(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(timedelta(minutes=10))
    assert provider.get_credentials() == ("default", "token-1")
    assert credentials.attempt_count == 1


def test_a_token_without_expiry_counts_as_fresh(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    credentials.token = "static-token"
    assert provider.get_credentials() == ("default", "static-token")
    assert credentials.attempt_count == 0


def test_a_stale_token_is_refreshed_by_a_caller_that_finds_the_refresh_idle(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(STALE_LIFETIME)
    assert provider.get_credentials() == ("default", "token-2")


def test_stale_callers_get_the_cached_token_while_another_caller_refreshes(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(STALE_LIFETIME)
    refresher = _start_blocked_refresh(provider=provider, credentials=credentials)
    results, callers = _start_callers(provider=provider, count=10)
    callers_returned = _join(callers)
    still_refreshing = refresher.is_alive()
    credentials.refresh_may_finish.set()
    _join([refresher])
    assert callers_returned
    assert still_refreshing
    assert results == [("default", "token-1")] * 10
    assert credentials.attempt_count == 2


def test_a_failed_stale_refresh_keeps_the_cached_token_and_holds_off_retries(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(STALE_LIFETIME)
    credentials.fail_next_refresh = True
    assert provider.get_credentials() == ("default", "token-1")
    assert _refresh_held_off(provider)


def test_logs_a_warning_when_a_stale_refresh_fails(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(STALE_LIFETIME)
    credentials.fail_next_refresh = True
    with capture_logs() as logs:
        provider.get_credentials()
    assert [(log["event"], log["log_level"]) for log in logs] == [("google_iam_token_refresh_failed", "warning")]


def test_stale_callers_do_not_refresh_during_the_hold_off(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(STALE_LIFETIME)
    credentials.fail_next_refresh = True
    provider.get_credentials()
    assert provider.get_credentials() == ("default", "token-1")
    assert credentials.attempt_count == 2


def test_stale_callers_refresh_again_after_the_hold_off(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(STALE_LIFETIME)
    credentials.fail_next_refresh = True
    provider.get_credentials()
    provider._retry_not_before = _now() - timedelta(seconds=1)  # pyright: ignore[reportPrivateUsage]
    assert provider.get_credentials() == ("default", "token-2")


def test_an_expired_token_is_refreshed(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(timedelta(seconds=-1))
    assert provider.get_credentials() == ("default", "token-2")


def test_a_failed_refresh_of_an_expired_token_raises_and_holds_off_retries(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(timedelta(seconds=-1))
    credentials.fail_next_refresh = True
    with pytest.raises(AuthenticationError) as raised:
        provider.get_credentials()
    assert isinstance(raised.value.__cause__, RefreshError)
    assert _refresh_held_off(provider)


def test_an_expired_token_raises_without_a_refresh_during_the_hold_off(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(timedelta(seconds=-1))
    _hold_off_refreshes(provider)
    with pytest.raises(AuthenticationError):
        provider.get_credentials()
    assert credentials.attempt_count == 1


def test_concurrent_callers_without_a_usable_token_share_one_refresh(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    credentials.refresh_may_finish.clear()
    results, callers = _start_callers(provider=provider, count=20)
    assert credentials.refresh_entered.wait(THREAD_TIMEOUT_SECONDS)
    credentials.refresh_may_finish.set()
    assert _join(callers)
    assert credentials.attempt_count == 1
    assert results == [("default", "token-1")] * 20


def test_a_stale_token_within_the_safety_margin_counts_as_expired(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(WITHIN_SAFETY_MARGIN)
    credentials.fail_next_refresh = True
    with pytest.raises(AuthenticationError):
        provider.get_credentials()


def test_a_stale_token_within_the_safety_margin_waits_for_a_refresh(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(WITHIN_SAFETY_MARGIN)
    refresher = _start_blocked_refresh(provider=provider, credentials=credentials)
    results, waiters = _start_callers(provider=provider, count=1)
    waiter_returned_early = _join(waiters, timeout_seconds=0.1)
    credentials.refresh_may_finish.set()
    assert _join([refresher, *waiters])
    assert not waiter_returned_early
    assert results == [("default", "token-2")]


def test_loads_credentials_once(provider: GoogleIamCredentialProvider, loader_calls: list[None]) -> None:
    for _ in range(3):
        provider.get_credentials()
    assert len(loader_calls) == 1


def test_loads_nothing_until_credentials_are_requested(provider: GoogleIamCredentialProvider, loader_calls: list[None]) -> None:
    assert loader_calls == []


def test_raises_when_a_refresh_yields_no_token(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    credentials.issue_empty_token = True
    with pytest.raises(AuthenticationError):
        provider.get_credentials()


def test_a_failing_loader_raises_an_authentication_error_chained_from_the_cause() -> None:
    def load() -> Credentials:
        raise DefaultCredentialsError("no credentials")

    with pytest.raises(AuthenticationError) as raised:
        GoogleIamCredentialProvider(credentials_loader=load).get_credentials()
    assert isinstance(raised.value.__cause__, DefaultCredentialsError)


def test_async_credentials_refresh_off_the_event_loop_thread(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    assert asyncio.run(provider.get_credentials_async()) == ("default", "token-1")
    assert credentials.refresh_thread is not threading.main_thread()


def test_async_credentials_serve_a_fresh_token_on_the_event_loop(provider: GoogleIamCredentialProvider, credentials: StubCredentials, monkeypatch: pytest.MonkeyPatch) -> None:
    provider.get_credentials()
    _forbid_threads(monkeypatch)
    assert asyncio.run(provider.get_credentials_async()) == ("default", "token-1")


def test_async_credentials_serve_a_stale_token_on_the_event_loop_during_the_hold_off(provider: GoogleIamCredentialProvider, credentials: StubCredentials, monkeypatch: pytest.MonkeyPatch) -> None:
    provider.get_credentials()
    credentials.expire_in(STALE_LIFETIME)
    _hold_off_refreshes(provider)
    _forbid_threads(monkeypatch)
    assert asyncio.run(provider.get_credentials_async()) == ("default", "token-1")


def test_async_credentials_serve_a_stale_token_on_the_event_loop_while_another_caller_refreshes(
    provider: GoogleIamCredentialProvider, credentials: StubCredentials, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider.get_credentials()
    credentials.expire_in(STALE_LIFETIME)
    refresher = _start_blocked_refresh(provider=provider, credentials=credentials)
    _forbid_threads(monkeypatch)
    try:
        assert asyncio.run(provider.get_credentials_async()) == ("default", "token-1")
    finally:
        credentials.refresh_may_finish.set()
        refresher.join(THREAD_TIMEOUT_SECONDS)


def test_async_credentials_refresh_a_stale_token_off_the_event_loop_thread(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(STALE_LIFETIME)
    assert asyncio.run(provider.get_credentials_async()) == ("default", "token-2")
    assert credentials.refresh_thread is not threading.main_thread()


def test_every_refresh_uses_the_same_request(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    credentials.expire_in(STALE_LIFETIME)
    provider.get_credentials()
    assert len(credentials.requests) == 2
    assert credentials.requests[0] is credentials.requests[1]


def test_refreshes_pass_the_refresh_timeout_to_the_transport(credentials: StubCredentials, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class RecordingRequest:
        def __call__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(provider_module, "Request", RecordingRequest)
    provider = _provider(credentials=credentials, loader_calls=[])
    provider.get_credentials()
    credentials.requests[0](url="https://example.test", method="GET")
    assert calls == [{"url": "https://example.test", "method": "GET", "timeout": REFRESH_TIMEOUT_SECONDS}]
