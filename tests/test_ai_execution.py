from aegis.ai_execution import AIExecutionEngine


class _DummyRuntime:
    def __init__(self):
        self.last_messages = None

    def generate(self, messages, temperature=0.2, max_tokens=512):
        self.last_messages = messages
        return "local-answer"

    def health(self):
        return True

    def runtime_profile(self):
        return {"threads": 8, "n_gpu_layers": 0, "ctx_size": 8192}


class _DummyMemory:
    def search(self, query, top_k=5, scope=None):
        return [
            {
                "id": "m1",
                "text": "AegisOS prefers local execution",
                "score": 0.9,
                "scope": scope or "long_term",
            }
        ]


def test_ai_execution_pipeline_uses_retrieval_context():
    runtime = _DummyRuntime()
    memory = _DummyMemory()
    engine = AIExecutionEngine(runtime, memory)

    result = engine.execute("how does aegisos run ai?", top_k=3, scope="long_term")

    assert result["response"] == "local-answer"
    assert result["retrieval_count"] == 1
    assert result["retrieval"][0]["id"] == "m1"
    assert runtime.last_messages is not None
    assert runtime.last_messages[1]["role"] == "system"
    assert "Retrieved memory context" in runtime.last_messages[1]["content"]


def test_ai_execution_health_reports_runtime():
    runtime = _DummyRuntime()
    memory = _DummyMemory()
    engine = AIExecutionEngine(runtime, memory)

    status = engine.health()

    assert status["runtime_available"] is True
    assert status["runtime_profile"]["threads"] == 8
