import json

from aegis.voice.wakeword import WakeWordDetector
from aegis.personalization import PersonalizationStore, PersonalizationEngine
from aegis.training.pipeline import LocalTrainingPipeline
from aegis.training.eval import LocalEvaluator


def test_wakeword_detector():
    detector = WakeWordDetector(wake_phrase="aegis")
    assert detector.detect("Hey Aegis do this")
    assert not detector.detect("hello assistant")


def test_personalization_store_and_engine(tmp_path):
    store = PersonalizationStore(db_path=str(tmp_path / "prefs.db"))
    engine = PersonalizationEngine(store=store)

    store.set_pref("verbosity", "concise")
    assert store.get_pref("verbosity") == "concise"

    engine.update_from_feedback("p", "r", positive=True)
    style = engine.inject_system_style()
    assert "verbosity=concise" in style


def test_local_training_pipeline_and_eval(tmp_path):
    pipeline = LocalTrainingPipeline(workspace=str(tmp_path / "train"))

    interactions = [{"prompt": "p1", "response": "r1", "positive": True}]
    dataset = pipeline.export_dataset(interactions)
    assert dataset.exists()

    bench = tmp_path / "bench.json"
    bench.write_text(json.dumps({"samples": [{"expected_pass": True}, {"expected_pass": False}]}), encoding="utf-8")

    evaluator = LocalEvaluator(str(bench))
    result = evaluator.evaluate("local-model")
    assert result["total"] == 2

    run = pipeline.run_training(["echo", "train-ok"])
    assert run["returncode"] == 0


def test_training_pipeline_returns_command_copy(tmp_path):
    pipeline = LocalTrainingPipeline(workspace=str(tmp_path / "train"))
    command = ["echo", "train"]

    result = pipeline.run_training(command)
    command.append("mutated")

    assert result["command"] == ["echo", "train"]
