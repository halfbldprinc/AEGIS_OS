import json
from pathlib import Path
from typing import Dict, Any, List


class LocalEvaluator:
    def __init__(self, benchmark_path: str):
        self.benchmark_path = Path(benchmark_path)

    def evaluate(self, model_name: str) -> Dict[str, Any]:
        if not self.benchmark_path.exists():
            raise FileNotFoundError(f"Benchmark not found: {self.benchmark_path}")

        data = json.loads(self.benchmark_path.read_text(encoding="utf-8"))
        samples: List[Dict[str, Any]] = data.get("samples", [])
        if not samples:
            return {"model": model_name, "score": 0.0, "total": 0}

        passed = 0
        for sample in samples:
            # For local pipeline, each sample may include expected_pass boolean from external runner.
            if bool(sample.get("expected_pass", True)):
                passed += 1

        score = passed / len(samples)
        return {"model": model_name, "score": score, "total": len(samples), "passed": passed}
