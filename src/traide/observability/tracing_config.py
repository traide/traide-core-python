import warnings
from enum import StrEnum
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter import cloud_trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor  # type: ignore
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID, SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult


class CloudTraceSpanExporterWithoutWarnings(cloud_trace.CloudTraceSpanExporter):
    """Suppresses DeprecationWarning raised by CloudTraceSpanExporter.

    See for details:
    https://github.com/GoogleCloudPlatform/opentelemetry-operations-python/issues/226
    """

    def export(self, *args: Any, **kwargs: Any) -> SpanExportResult:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=DeprecationWarning)
            return super().export(*args, **kwargs)


class TracingType(StrEnum):
    CONSOLE = "CONSOLE"
    GCP = "GCP"


def configure_tracing(service_name: str, hostname: str, tracing_type: TracingType) -> TracerProvider:
    # https://github.com/GoogleCloudPlatform/opentelemetry-operations-python/blob/main/samples/instrumentation-quickstart/setup_opentelemetry.py
    resource = Resource.create(
        attributes={
            SERVICE_NAME: service_name,
            SERVICE_INSTANCE_ID: hostname,
        }
    )

    traceProvider = TracerProvider(resource=resource)
    if tracing_type == TracingType.CONSOLE:
        traceProvider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        google_trace_exporter = BatchSpanProcessor(CloudTraceSpanExporterWithoutWarnings())  # type: ignore
        traceProvider.add_span_processor(google_trace_exporter)
    trace.set_tracer_provider(traceProvider)

    reader = PrometheusMetricReader()
    meterProvider = MeterProvider(metric_readers=[reader], resource=resource)
    metrics.set_meter_provider(meterProvider)

    SQLAlchemyInstrumentor().instrument(enable_commenter=True, commenter_options={})

    return traceProvider
