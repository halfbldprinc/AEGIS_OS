"""Command line interface for AegisOS local assistant runtime and API."""

import argparse
import json
import logging
import os
import signal
import subprocess
import time
from typing import Optional

from .api import app
from .daemon import AegisDaemon
from .logging import configure_logging


from pathlib import Path

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis", description="AegisOS integrated local AI assistant service")

    subparsers = parser.add_subparsers(dest="command", required=True)

    daemon_parser = subparsers.add_parser("daemon", help="Run Aegis daemon cycle loop")
    daemon_parser.add_argument("--iterations", type=int, default=1, help="Number of daemon cycles to execute")

    api_parser = subparsers.add_parser("api", help="Run FastAPI HTTP API")
    api_parser.add_argument("--host", default="127.0.0.1", help="API bind host")
    api_parser.add_argument("--port", type=int, default=8000, help="API bind port")

    plan_parser = subparsers.add_parser("plan", help="Plan operations")
    plan_parser.add_argument("--simulate", action="store_true", help="Simulate a plan instead of executing")
    plan_parser.add_argument("--step", action="append", help="Plan step in skill:action:param format (JSON optional)")

    agent_parser = subparsers.add_parser("agent", help="Agent lifecycle operations")
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", required=True)
    agent_run_parser = agent_subparsers.add_parser("run", help="Run persistent voice monitoring service")
    agent_run_parser.add_argument(
        "--no-wakeword",
        action="store_true",
        help="Accept voice commands without requiring wake word",
    )
    agent_run_parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.2,
        help="Voice polling interval in seconds",
    )
    start_parser = agent_subparsers.add_parser("start", help="Alias for 'agent run' (foreground)")
    start_parser.add_argument(
        "--no-wakeword",
        action="store_true",
        help="Accept voice commands without requiring wake word",
    )
    start_parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.2,
        help="Voice polling interval in seconds",
    )
    text_fallback_parser = agent_subparsers.add_parser(
        "text-fallback",
        help="Run text-command fallback loop for desktop sessions when microphone is unavailable",
    )
    text_fallback_parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds between availability checks",
    )
    agent_subparsers.add_parser("stop", help="Stop voice monitoring daemon")
    agent_subparsers.add_parser("status", help="Check agent daemon status")

    ops_parser = subparsers.add_parser("ops", help="Operations and reliability commands")
    ops_subparsers = ops_parser.add_subparsers(dest="ops_command", required=True)

    soak_parser = ops_subparsers.add_parser("soak", help="Run soak cycles")
    soak_parser.add_argument("--cycles", type=int, default=100, help="Number of daemon cycles")
    soak_parser.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between cycles")

    chaos_parser = ops_subparsers.add_parser("chaos", help="Run a chaos scenario")
    chaos_parser.add_argument("--scenario", required=True, choices=["llm_restart", "voice_interrupt"], help="Chaos scenario name")

    eval_parser = ops_subparsers.add_parser("eval-harness", help="Compute orchestrator reliability and performance KPIs")
    eval_parser.add_argument("--audit-log", default=".aegis/audit.log", help="Path to orchestrator audit log")
    eval_parser.add_argument("--since-hours", type=float, default=24.0, help="Time window to evaluate")
    eval_parser.add_argument(
        "--snapshot-out",
        default=".aegis/orchestrator-eval-history.jsonl",
        help="Path to append JSONL KPI snapshots",
    )

    llm_parser = subparsers.add_parser("llm", help="Local LLM runtime and model manager")
    llm_subparsers = llm_parser.add_subparsers(dest="llm_command", required=True)

    llm_subparsers.add_parser("start", help="Start LLM server process")
    llm_subparsers.add_parser("stop", help="Stop LLM server process")
    llm_subparsers.add_parser("status", help="Get LLM runtime status")

    swap_parser = llm_subparsers.add_parser("swap", help="Swap active model")
    swap_parser.add_argument("model_name", help="Model name to activate")

    llm_subparsers.add_parser("list", help="List downloaded models")

    download_parser = llm_subparsers.add_parser("download", help="Download a model from HuggingFace")
    download_parser.add_argument("--repo", required=True, help="HuggingFace repo slug")
    download_parser.add_argument("--filename", required=True, help="Model filename within repo")
    download_parser.add_argument("--target-dir", default=str(Path.home() / ".aegis" / "models"), help="Directory to store downloaded models")

    return parser


def run_daemon(iterations: int = 1) -> None:
    logger = logging.getLogger("aegis.cli")
    logger.info("Starting daemon run cycles: %d", iterations)

    daemon = AegisDaemon()
    for i in range(iterations):
        logger.debug("Daemon cycle %d/%d", i + 1, iterations)
        daemon.run_cycle()

    logger.info("Daemon run completed")


def run_api(host: str = "127.0.0.1", port: int = 8000) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("uvicorn is required to run the API server") from exc

    logger = logging.getLogger("aegis.cli")
    logger.info("Starting API server at %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


def run_agent(wakeword_required: bool = True, poll_interval: float = 0.2) -> None:
    logger = logging.getLogger("aegis.cli")
    daemon = AegisDaemon()
    daemon.start()

    mic_ready = True
    mic_reason = "microphone status unknown"
    mic_source = getattr(daemon.voice_session, "microphone_source", None)
    if mic_source is None:
        mic_ready = False
        mic_reason = "No microphone source configured"
    elif hasattr(mic_source, "backend_status"):
        try:
            mic_ready, mic_reason = mic_source.backend_status()
        except Exception as exc:
            mic_ready = False
            mic_reason = f"Microphone probe failed: {exc}"

    if mic_ready:
        daemon.start_voice_monitoring(wakeword_required=wakeword_required, poll_interval=poll_interval)
        logger.info(
            "Voice monitoring active (wakeword_required=%s, poll_interval=%.2fs)",
            wakeword_required,
            poll_interval,
        )
    else:
        logger.warning("Microphone unavailable; switching to text-command input: %s", mic_reason)

    stop_requested = False

    def _request_stop(signum, _frame):
        nonlocal stop_requested
        logger.info("Received signal %s, stopping voice agent", signum)
        stop_requested = True

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    try:
        while not stop_requested:
            if mic_ready:
                time.sleep(0.5)
                continue

            if _has_graphical_session() and _has_zenity():
                text = _prompt_text_command_gui()
                if stop_requested:
                    break
                if text is None:
                    time.sleep(0.3)
                    continue
                if not text.strip():
                    time.sleep(0.2)
                    continue
                _execute_text_command(daemon, text)
                continue

            text = _prompt_text_command_terminal()
            if not text:
                time.sleep(0.3)
                continue
            _execute_text_command(daemon, text)
    finally:
        daemon.shutdown()
        logger.info("Voice agent stopped")


def run_text_fallback(poll_interval: float = 1.0) -> None:
    logger = logging.getLogger("aegis.cli")
    daemon = AegisDaemon()
    daemon.start()

    stop_requested = False

    def _request_stop(signum, _frame):
        nonlocal stop_requested
        logger.info("Received signal %s, stopping text fallback", signum)
        stop_requested = True

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    try:
        while not stop_requested:
            mic_ready = False
            mic_source = getattr(daemon.voice_session, "microphone_source", None)
            if mic_source is not None and hasattr(mic_source, "backend_status"):
                try:
                    mic_ready, _ = mic_source.backend_status()
                except Exception:
                    mic_ready = False

            if mic_ready:
                time.sleep(max(0.2, poll_interval))
                continue

            if _has_graphical_session() and _has_zenity():
                text = _prompt_text_command_gui()
                if stop_requested:
                    break
                if text is None:
                    time.sleep(0.3)
                    continue
                if not text.strip():
                    time.sleep(0.2)
                    continue
                _execute_text_command(daemon, text)
                continue

            time.sleep(max(0.2, poll_interval))
    finally:
        daemon.shutdown()
        logger.info("Text fallback stopped")


def _has_graphical_session() -> bool:
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


def _has_zenity() -> bool:
    try:
        completed = subprocess.run(
            ["zenity", "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _prompt_text_command_gui() -> Optional[str]:
    cmd = [
        "zenity",
        "--entry",
        "--always-on-top",
        "--title=AegisOS Assistant",
        "--text=Microphone not available. Type your command for AegisOS:",
        "--entry-text=",
        "--width=640",
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        return None

    if completed.returncode != 0:
        return ""
    return (completed.stdout or "").strip()


def _prompt_text_command_terminal() -> str:
    try:
        return input("AegisOS command> ").strip()
    except EOFError:
        return ""


def _execute_text_command(daemon: AegisDaemon, text: str) -> None:
    logger = logging.getLogger("aegis.cli")
    plan = daemon.create_plan_from_instruction(text)
    result = daemon.execute_plan_by_id(plan.id, allow_failure=False)

    if result.get("requires_approval"):
        summary = "Request needs approval. Confirm in local prompt and retry if needed."
    elif result.get("status") == "SUCCEEDED":
        summary = "Done"
    else:
        summary = f"Status: {result.get('status', 'unknown')}"

    logger.info("Text command executed: %s -> %s", text, summary)
    if _has_graphical_session() and _has_zenity():
        try:
            subprocess.run(
                [
                    "zenity",
                    "--notification",
                    "--text",
                    f"AegisOS: {summary}",
                ],
                check=False,
            )
        except OSError:
            pass


def main(argv: Optional[list[str]] = None) -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "daemon":
        run_daemon(iterations=args.iterations)
    elif args.command == "api":
        run_api(host=args.host, port=args.port)
    elif args.command == "plan":
        from .orchestrator import Orchestrator, Plan

        o = Orchestrator()
        p = Plan()
        if args.step:
            for raw in args.step:
                parts = raw.split(":", 2)
                if len(parts) < 2:
                    continue
                skill_name, action = parts[0], parts[1]
                params = {}
                if len(parts) == 3:
                    try:
                        params = json.loads(parts[2])
                    except Exception:
                        params = {}
                p.add_step(skill_name=skill_name, action=action, params=params)

        if args.simulate:
            result = o.simulate_plan(p)
        else:
            result = o.execute_plan(p, allow_failure=True)

        print(result)
    elif args.command == "agent":
        if args.agent_command in {"run", "start"}:
            run_agent(wakeword_required=not args.no_wakeword, poll_interval=max(0.05, float(args.poll_interval)))
        elif args.agent_command == "text-fallback":
            run_text_fallback(poll_interval=max(0.2, float(args.poll_interval)))
        elif args.agent_command == "stop":
            print("Use systemctl stop aegis-agent.service for integrated Linux deployments")
        elif args.agent_command == "status":
            print({"voice_monitor_running": "unknown", "hint": "Use systemctl status aegis-agent.service"})
    elif args.command == "ops":
        daemon = AegisDaemon()
        if args.ops_command == "soak":
            print(daemon.run_soak_test(cycles=args.cycles, sleep_s=args.sleep))
        elif args.ops_command == "chaos":
            print(daemon.run_chaos_scenario(args.scenario))
        elif args.ops_command == "eval-harness":
            from .audit import AuditLog
            from .orchestrator.eval_harness import OrchestratorEvaluationHarness

            harness = OrchestratorEvaluationHarness()
            summary = harness.evaluate_from_audit_log(AuditLog(path=Path(args.audit_log)), since_hours=args.since_hours)
            harness.append_snapshot(args.snapshot_out, summary)
            print(json.dumps(summary.to_dict(), indent=2))
    elif args.command == "llm":
        from .llm import LLMRuntime, ModelManager

        models_dir = Path.home() / ".aegis" / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        manager = ModelManager(models_dir=models_dir)
        runtime = LLMRuntime(model_path=manager.get_active_model_path() or str(models_dir / "primary-q4km.gguf"))

        if args.llm_command == "start":
            runtime.start()
            print("LLM runtime started")
        elif args.llm_command == "stop":
            runtime.stop()
            print("LLM runtime stopped")
        elif args.llm_command == "status":
            active = manager.get_active_model() or {}
            alive = runtime.health()
            print({"active_model": active.get("name"), "active_path": active.get("path"), "llm_alive": alive})
        elif args.llm_command == "list":
            print(json.dumps(manager.list_models(), indent=2))
        elif args.llm_command == "swap":
            activated_path = manager.set_active(args.model_name)
            runtime.swap_model(activated_path)
            print(f"Swapped active model to {args.model_name}")
        elif args.llm_command == "download":
            path = manager.download_model(args.repo, args.filename, args.target_dir)
            print(f"Downloaded model to {path}")


if __name__ == "__main__":
    main()
