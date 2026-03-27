import json
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List

from .eval import LocalEvaluator


class LocalTrainingPipeline:
    def __init__(self, workspace: str = "~/.aegis/training"):
        self.workspace = Path(workspace).expanduser()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def export_dataset(self, interactions: List[Dict[str, Any]], out_name: str = "dataset.jsonl") -> Path:
        out = self.workspace / out_name
        with out.open("w", encoding="utf-8") as f:
            for item in interactions:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return out

    def run_training(self, command: List[str], timeout: int = 7200) -> Dict[str, Any]:
        started = time.perf_counter()
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        elapsed = time.perf_counter() - started
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "elapsed_s": elapsed,
            "command": list(command),
        }

    def train_and_evaluate(
        self,
        interactions: List[Dict[str, Any]],
        train_command: List[str],
        benchmark_path: str,
        model_name: str,
    ) -> Dict[str, Any]:
        dataset = self.export_dataset(interactions)
        run_result = self.run_training(train_command)

        evaluator = LocalEvaluator(benchmark_path)
        eval_result = evaluator.evaluate(model_name)

        return {
            "dataset": str(dataset),
            "training": run_result,
            "evaluation": eval_result,
        }
