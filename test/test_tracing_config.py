from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from google.oauth2.credentials import Credentials
from opentelemetry.sdk.trace import TracerProvider
from requests import PreparedRequest, Response
from requests.adapters import HTTPAdapter

from traide.observability.tracing_config import (
    CLOUD_PLATFORM_SCOPE,
    GCP_PROJECT_ID,
    TELEMETRY_TRACES_ENDPOINT,
    MissingGcpProjectError,
    TracingType,
    configure_tracing,
)

PROJECT_ID = "traide-ai-test"
TOKEN = "test-token"


def test_gcp_tracing_posts_spans_to_the_telemetry_api_with_the_credentials_token(
    sent_requests: list[PreparedRequest],
) -> None:
    with _application_default_credentials(project_id=PROJECT_ID):
        provider = _configure(TracingType.GCP)

    provider.get_tracer(__name__).start_span("unit-of-work").end()
    provider.force_flush()

    assert [request.url for request in sent_requests] == [TELEMETRY_TRACES_ENDPOINT]
    assert sent_requests[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_gcp_tracing_tags_the_resource_with_the_credentials_project() -> None:
    with _application_default_credentials(project_id=PROJECT_ID):
        console_provider = _configure(TracingType.CONSOLE)
        gcp_provider = _configure(TracingType.GCP)

    assert GCP_PROJECT_ID not in console_provider.resource.attributes
    assert gcp_provider.resource.attributes[GCP_PROJECT_ID] == PROJECT_ID


def test_gcp_tracing_requests_the_cloud_platform_scope() -> None:
    with _application_default_credentials(project_id=PROJECT_ID) as default:
        _configure(TracingType.GCP)

    default.assert_called_once_with(scopes=[CLOUD_PLATFORM_SCOPE])


def test_gcp_tracing_without_a_credentials_project_raises() -> None:
    with _application_default_credentials(project_id=None), pytest.raises(MissingGcpProjectError):
        _configure(TracingType.GCP)


@pytest.fixture
def sent_requests() -> Iterator[list[PreparedRequest]]:
    sent: list[PreparedRequest] = []

    def send(_adapter: HTTPAdapter, request: PreparedRequest, **_kwargs: Any) -> Response:
        sent.append(request)
        response = Response()
        response.status_code = 200
        return response

    with patch.object(HTTPAdapter, "send", autospec=True, side_effect=send):
        yield sent


@contextmanager
def _application_default_credentials(project_id: str | None) -> Generator[MagicMock, None, None]:
    with patch("google.auth.default", return_value=(Credentials(token=TOKEN), project_id)) as default:
        yield default


def _configure(tracing_type: TracingType) -> TracerProvider:
    return configure_tracing(service_name="svc", hostname="host", tracing_type=tracing_type)
