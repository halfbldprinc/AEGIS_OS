import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class Quantizer:
    def __init__(self, llama_quantize_executable: str = "llama-quantize"):
        self.llama_quantize_executable = llama_quantize_executable

    def quantize(self, input_gguf: str, output_gguf: str, quant_type: str) -> dict:
        input_path = Path(input_gguf).expanduser()
        output_path = Path(output_gguf).expanduser()

        if not input_path.exists():
            raise FileNotFoundError(f"Input model not found: {input_path}")

        start = time.time()
        cmd = [self.llama_quantize_executable, str(input_path), str(output_path), quant_type]
        logger.info("Quantizer running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error("Quantization failed: %s", result.stderr.strip())
            raise RuntimeError("Quantization failed")

        duration = time.time() - start
        size_bytes = output_path.stat().st_size if output_path.exists() else 0

        return {
            "output_path": str(output_path),
            "size_bytes": size_bytes,
            "duration_seconds": duration,
            "quant_type": quant_type,
        }
