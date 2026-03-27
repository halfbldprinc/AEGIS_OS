"""Tests for first-boot interactive wizard."""

import json
import tempfile
from pathlib import Path

import pytest

from aegis.firstboot_wizard import FirstBootWizard


def test_firstboot_wizard_init(tmp_path):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    assert wizard.completed is False
    assert len(wizard.responses) == 0


def test_firstboot_wizard_should_run(tmp_path):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    assert wizard.should_run() is True
    
    wizard.completed = True
    assert wizard.should_run() is False


def test_firstboot_wizard_save_and_load(tmp_path):
    state_path = tmp_path / "firstboot_state.json"
    
    # Create and save
    wizard1 = FirstBootWizard(state_path=state_path)
    wizard1.responses["model_selection"] = "balanced"
    wizard1.responses["security_profile"] = "strict"
    wizard1.completed = True
    wizard1._save_state()
    
    # Load
    wizard2 = FirstBootWizard(state_path=state_path)
    assert wizard2.completed is True
    assert wizard2.responses["model_selection"] == "balanced"
    assert wizard2.responses["security_profile"] == "strict"


def test_firstboot_wizard_responses_empty(tmp_path):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    assert wizard.get_responses() == {}


def test_firstboot_wizard_responses_populated(tmp_path):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    wizard.responses["model_selection"] = "large"
    wizard.responses["voice_enabled"] = True
    
    responses = wizard.get_responses()
    assert responses["model_selection"] == "large"
    assert responses["voice_enabled"] is True


def test_firstboot_model_selection_lightweight(tmp_path, monkeypatch):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "1")
    
    result = wizard.ask_model_selection()
    assert result == "lightweight"
    assert wizard.responses["model_selection"] == "lightweight"


def test_firstboot_model_selection_balanced(tmp_path, monkeypatch):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "balanced")
    
    result = wizard.ask_model_selection()
    assert result == "balanced"
    assert wizard.responses["model_selection"] == "balanced"


def test_firstboot_model_selection_skipped(tmp_path, monkeypatch):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "skip")
    
    result = wizard.ask_model_selection()
    assert result is None
    assert wizard.responses["model_selection"] == "deferred"


def test_firstboot_model_selection_invalid(tmp_path, monkeypatch):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "99")
    
    result = wizard.ask_model_selection()
    assert result is None
    assert wizard.responses["model_selection"] == "deferred"


def test_firstboot_policy_strict(tmp_path, monkeypatch):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "1")
    
    result = wizard.ask_policy_profile()
    assert result == "strict"
    assert wizard.responses["security_profile"] == "strict"


def test_firstboot_policy_default_skip(tmp_path, monkeypatch):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "skip")
    
    result = wizard.ask_policy_profile()
    assert result == "balanced"
    assert wizard.responses["security_profile"] == "balanced"


def test_firstboot_voice_enabled(tmp_path, monkeypatch):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "yes")
    
    result = wizard.ask_voice_enable()
    assert result is True
    assert wizard.responses["voice_enabled"] is True


def test_firstboot_voice_disabled(tmp_path, monkeypatch):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "no")
    
    result = wizard.ask_voice_enable()
    assert result is False
    assert wizard.responses["voice_enabled"] is False


def test_firstboot_voice_skipped(tmp_path, monkeypatch):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "skip")
    
    result = wizard.ask_voice_enable()
    assert result is False
    assert wizard.responses["voice_enabled"] is False


def test_firstboot_memory_enabled(tmp_path, monkeypatch):
    wizard = FirstBootWizard(state_path=tmp_path / "state.json")
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "yes")
    
    result = wizard.ask_memory_integration()
    assert result is True
    assert wizard.responses["memory_enabled"] is True


def test_firstboot_completed_state(tmp_path):
    state_path = tmp_path / "state.json"
    wizard = FirstBootWizard(state_path=state_path)
    
    assert wizard.should_run() is True
    wizard.completed = True
    wizard._save_state()
    
    # Reload
    wizard2 = FirstBootWizard(state_path=state_path)
    assert wizard2.should_run() is False
