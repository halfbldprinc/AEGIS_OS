# Calamares Installer Integration

This folder provides a Calamares shellprocess module configuration for true installer-stage AegisOS selection.

## Goal
During installation, user selects:
- model provider (for example `deepseek`)
- model size (for example `1.5b`, `7b`, `14b`)
- permission profile (`strict`, `prompt_once`, `balanced`, `open`)

Each model option includes a requirement bar with minimum RAM, ROM/storage, CPU cores, and GPU/VRAM need.
The menu attempts online discovery from free provider catalogs (Hugging Face and Ollama) and falls back to
the local `model_catalog.json` if networking is unavailable.

Selections are written to:
- `/etc/aegis/install-selections.env` in the target rootfs

The installed system onboarding service reads this file and performs non-interactive provisioning.

## How to Wire
1. Ensure AegisOS files are available in installer environment at `/opt/aegisos`.
2. Copy `deploy/calamares/modules/aegis_model_select.conf` into Calamares module path.
3. Add `aegis_model_select` to the Calamares module sequence before final install commit.
4. Ensure installer environment includes `whiptail` (or `dialog`) for menu UI.
