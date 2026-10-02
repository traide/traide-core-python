from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

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
    gcp_credentials,
    gcp_span_processor,
)

PROJECT_ID = "traide-ai-test"
TOKEN = "test-token"


def test_gcp_span_processor_posts_spans_to_the_telemetry_api_with_the_credentials_token(
    sent_requests: list[PreparedRequest],
) -> None:
    provider = TracerProvider()
    provider.add_span_processor(gcp_span_processor(Credentials(token=TOKEN)))

    provider.get_tracer(__name__).start_span("unit-of-work").end()
    provider.force_flush()

    assert [request.url for request in sent_requests] == [TELEMETRY_TRACES_ENDPOINT]
    assert sent_requests[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_gcp_tracing_tags_the_resource_with_the_credentials_project() -> None:
    with patch("google.auth.default", return_value=(Credentials(token=TOKEN), PROJECT_ID)):
        console_provider = configure_tracing(service_name="svc", hostname="host", tracing_type=TracingType.CONSOLE)
        gcp_provider = configure_tracing(service_name="svc", hostname="host", tracing_type=TracingType.GCP)

    assert GCP_PROJECT_ID not in console_provider.resource.attributes
    assert gcp_provider.resource.attributes[GCP_PROJECT_ID] == PROJECT_ID


def test_gcp_credentials_request_the_cloud_platform_scope() -> None:
    with patch("google.auth.default", return_value=(Credentials(token=TOKEN), PROJECT_ID)) as default:
        assert gcp_credentials()[1] == PROJECT_ID

    default.assert_called_once_with(scopes=[CLOUD_PLATFORM_SCOPE])


def test_gcp_credentials_without_a_project_raise() -> None:
    with (
        patch("google.auth.default", return_value=(Credentials(token=TOKEN), None)),
        pytest.raises(MissingGcpProjectError),
    ):
        gcp_credentials()


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
