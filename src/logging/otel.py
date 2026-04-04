"""
ARGOS-2 — OpenTelemetry Bootstrap.

Initializes the TracerProvider with OTLP gRPC exporter targeting Jaeger.
This module is imported once at server startup; all other modules use get_tracer().

Configuration (via environment):
  - OTEL_EXPORTER_OTLP_ENDPOINT: gRPC endpoint (default: http://localhost:4317)
  - OTEL_SERVICE_NAME: Service name tag (default: argos-api)
"""

import logging
import os

logger = logging.getLogger("argos")

_tracer = None


def init_otel():
    """
    Initializes OpenTelemetry tracing with OTLP exporter.
    Safe to call multiple times (idempotent).
    Returns the configured tracer.
    """
    global _tracer
    if _tracer is not None:
        return _tracer

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    service_name = os.environ.get("OTEL_SERVICE_NAME", "argos-api")

    if not endpoint:
        logger.info("[OTel] OTEL_EXPORTER_OTLP_ENDPOINT not set — tracing disabled.")
        _tracer = _NoOpTracer()
        return _tracer

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("argos", "2.1.0")

        logger.info(f"[OTel] Tracing initialized → {endpoint} (service={service_name})")
        return _tracer

    except ImportError:
        logger.warning(
            "[OTel] opentelemetry packages not installed — tracing disabled."
        )
        _tracer = _NoOpTracer()
        return _tracer
    except Exception as e:
        logger.warning(f"[OTel] Failed to initialize: {e} — tracing disabled.")
        _tracer = _NoOpTracer()
        return _tracer


def get_tracer():
    """Returns the global tracer. Initializes OTel if not done yet."""
    global _tracer
    if _tracer is None:
        return init_otel()
    return _tracer


# ---------------------------------------------------------------------------
# No-Op Tracer (when OTel is disabled or unavailable)
# ---------------------------------------------------------------------------


class _NoOpSpan:
    """A span that does nothing — zero overhead when tracing is off."""

    def set_attribute(self, key, value):
        pass

    def set_status(self, status):
        pass

    def record_exception(self, exc):
        pass

    def end(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoOpTracer:
    """A tracer that returns no-op spans."""

    def start_as_current_span(self, name, **kwargs):
        return _NoOpSpan()

    def start_span(self, name, **kwargs):
        return _NoOpSpan()
