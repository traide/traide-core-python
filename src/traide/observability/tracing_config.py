from enum import StrEnum

from opentelemetry import metrics, trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter  # type: ignore
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor  # type: ignore
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID, SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


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
        google_trace_exporter = BatchSpanProcessor(CloudTraceSpanExporter())  # type: ignore
        traceProvider.add_span_processor(google_trace_exporter)
    trace.set_tracer_provider(traceProvider)

    reader = PrometheusMetricReader()
    meterProvider = MeterProvider(metric_readers=[reader], resource=resource)
    metrics.set_meter_provider(meterProvider)

    SQLAlchemyInstrumentor().instrument(enable_commenter=True, commenter_options={})

    return traceProvider
