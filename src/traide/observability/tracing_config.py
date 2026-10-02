from enum import StrEnum
from typing import cast

import google.auth
from google.auth.credentials import Credentials
from google.auth.transport.requests import AuthorizedSession
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor  # type: ignore
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID, SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
GCP_PROJECT_ID = "gcp.project_id"
TELEMETRY_TRACES_ENDPOINT = "https://telemetry.googleapis.com/v1/traces"


class TracingType(StrEnum):
    CONSOLE = "CONSOLE"
    GCP = "GCP"


class MissingGcpProjectError(RuntimeError):
    pass


def configure_tracing(service_name: str, hostname: str, tracing_type: TracingType) -> TracerProvider:
    # https://github.com/GoogleCloudPlatform/opentelemetry-operations-python/blob/main/samples/otlptrace/example_http.py
    attributes = {
        SERVICE_NAME: service_name,
        SERVICE_INSTANCE_ID: hostname,
    }
    if tracing_type == TracingType.CONSOLE:
        span_processor = BatchSpanProcessor(OTLPSpanExporter())
    else:
        credentials, project_id = _gcp_credentials()
        attributes[GCP_PROJECT_ID] = project_id
        span_processor = _gcp_span_processor(credentials)
    resource = Resource.create(attributes=attributes)

    traceProvider = TracerProvider(resource=resource)
    traceProvider.add_span_processor(span_processor)
    trace.set_tracer_provider(traceProvider)

    reader = PrometheusMetricReader()
    meterProvider = MeterProvider(metric_readers=[reader], resource=resource)
    metrics.set_meter_provider(meterProvider)

    SQLAlchemyInstrumentor().instrument(enable_commenter=True, commenter_options={})

    return traceProvider


def _gcp_credentials() -> tuple[Credentials, str]:
    credentials, project_id = cast(
        tuple[Credentials, str | None],
        google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE]),  # pyright: ignore[reportUnknownMemberType]
    )
    if not project_id:
        raise MissingGcpProjectError("Application Default Credentials name no GCP project")
    return credentials, project_id


def _gcp_span_processor(credentials: Credentials) -> SpanProcessor:
    exporter = OTLPSpanExporter(endpoint=TELEMETRY_TRACES_ENDPOINT, session=AuthorizedSession(credentials))
    return BatchSpanProcessor(exporter)
