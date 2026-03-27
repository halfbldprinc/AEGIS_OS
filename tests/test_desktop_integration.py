from aegis.desktop_integration import DesktopIntegrationManager


def test_desktop_integration_dry_run(tmp_path):
    manager = DesktopIntegrationManager(api_base_url="http://127.0.0.1:8000")

    result = manager.install_user_hooks(home_dir=str(tmp_path), dry_run=True)

    assert result["status"] == "planned"
    assert result["files"]["helper_script"].endswith(".local/bin/aegis-ask")


def test_desktop_integration_install_and_status(tmp_path):
    manager = DesktopIntegrationManager(api_base_url="http://127.0.0.1:8000")

    result = manager.install_user_hooks(home_dir=str(tmp_path), dry_run=False)

    assert result["status"] == "installed"
    status = manager.status(home_dir=str(tmp_path))
    assert status["helper_script_installed"] is True
    assert status["launcher_installed"] is True
    assert status["file_manager_action_installed"] is True
    assert status["terminal_alias_installed"] is True
