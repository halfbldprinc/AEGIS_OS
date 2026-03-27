import logging
from typing import Dict, Any

try:
    from opentelemetry import trace
except ImportError:
    trace = None

logger = logging.getLogger(__name__)


class TelemetryManager:
    """Unified telemetry manager for metrics and distributed traces."""

    def __init__(self):
        self.metrics: Dict[str, float] = {}

    def record_metric(self, name: str, value: float, labels: Dict[str, str] | None = None) -> None:
        metric_key = name if labels is None else f"{name}|{sorted(labels.items())}"
        self.metrics[metric_key] = float(value)
        logger.debug("Telemetry metric recorded %s=%s labels=%s", name, value, labels)

    def get_metric(self, name: str, labels: Dict[str, str] | None = None) -> float:
        metric_key = name if labels is None else f"{name}|{sorted(labels.items())}"
        return self.metrics.get(metric_key, 0.0)

    def get_all_metrics(self) -> Dict[str, float]:
        return dict(self.metrics)

    def start_trace(self, span_name: str, attributes: Dict[str, Any] | None = None):
        if trace is None:
            logger.debug("OpenTelemetry not installed; skipping trace %s", span_name)
            return None

        tracer = trace.get_tracer(__name__)
        span_context = tracer.start_as_current_span(span_name)
        try:
            span = span_context.__enter__()
        except Exception:
            logger.exception("Failed to start trace span %s", span_name)
            return None

        if attributes:
            for k, v in attributes.items():
                try:
                    span.set_attribute(k, v)
                except Exception:
                    logger.debug("Unable to set trace attribute %s", k)
        return span_context

    def stop_trace(self, span) -> None:
        if span is None:
            return
        try:
            span.__exit__(None, None, None)
        except Exception:
            logger.exception("Exception while stopping trace")

    def exporter_text(self) -> str:
        lines = ["# HELP aegis_telemetry_metric Global Aegis telemetry metric", "# TYPE aegis_telemetry_metric gauge"]
        for key, value in self.metrics.items():
            lines.append(f"aegis_telemetry_metric{{name=\"{key}\"}} {value}")
        return "\n".join(lines)
