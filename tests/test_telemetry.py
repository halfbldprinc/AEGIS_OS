from aegis.telemetry import TelemetryManager


class _FakeSpan:
    def __init__(self):
        self.attrs = {}

    def set_attribute(self, key, value):
        self.attrs[key] = value


class _FakeSpanContext:
    def __init__(self):
        self.span = _FakeSpan()
        self.exited = False

    def __enter__(self):
        return self.span

    def __exit__(self, exc_type, exc, tb):
        self.exited = True


class _FakeTracer:
    def __init__(self):
        self.last_context = None

    def start_as_current_span(self, _name):
        self.last_context = _FakeSpanContext()
        return self.last_context


class _FakeTraceModule:
    def __init__(self):
        self.tracer = _FakeTracer()

    def get_tracer(self, _name):
        return self.tracer


def test_telemetry_start_trace_sets_attributes_and_stop_closes(monkeypatch):
    from aegis import telemetry as telemetry_module

    fake_trace = _FakeTraceModule()
    monkeypatch.setattr(telemetry_module, "trace", fake_trace)

    manager = TelemetryManager()
    span_ctx = manager.start_trace("plan.execute", attributes={"plan_id": "p1", "step": 2})

    assert span_ctx is not None
    assert fake_trace.tracer.last_context.span.attrs == {"plan_id": "p1", "step": 2}

    manager.stop_trace(span_ctx)
    assert fake_trace.tracer.last_context.exited is True


def test_telemetry_start_trace_without_backend_returns_none(monkeypatch):
    from aegis import telemetry as telemetry_module

    monkeypatch.setattr(telemetry_module, "trace", None)

    manager = TelemetryManager()
    assert manager.start_trace("noop") is None
