# AegisOS Integrated Linux Instructions

This guide is for non-technical users and walks from Linux install to first AI task.

## Flow (important)
- Linux-integrated services start and stay ready always.
- Use wake-word voice command for normal usage.
- If no microphone is available, use the always-on-top text input popup.

## What you are installing

AegisOS runs a local AI assistant built into Linux boot and service lifecycle.

It has three phases:
1. Build and install Linux image.
2. First-boot onboarding (model + permissions).
3. Run first AI task through the always-on listening agent.
4. Upgrade model size later when needed.
5. Change permission profile later when needed.

---

## Build and install AegisOS Linux image

Use this flow to deploy AegisOS as an integrated Linux system.

### 1) Build the Debian live ISO

```bash
./scripts/build_iso_debian_live.sh
```

### 2) Validate ISO evidence (optional but recommended)

```bash
./scripts/validate_iso_evidence.sh --build
```

### 3) Install/boot the ISO

During install/first boot:
- You will be asked to choose model provider + size.
- You will be asked to choose permission profile.

What happens in background on integrated install:
- Runtime is installed into `/opt/aegisos`.
- Onboarding service runs once and writes completion stamp at `/var/lib/aegis/.firstboot_done`.
- API service runs as user `aegis` on `127.0.0.1:8000`.
- Voice agent service runs continuously and listens for the wake word `aegis`.
- If no microphone is available, AegisOS automatically shows an always-on-top text command input in the Linux desktop session (no curl, no manual POST).

You can also install directly into a Linux root filesystem pipeline:

```bash
sudo ./scripts/install_distro_rootfs.sh
```

---

## Your first AI task

### 1) Check integrated services

```bash
sudo systemctl status aegis-onboarding.service aegis-api.service aegis-agent.service --no-pager
```

You should see services in active/running state (onboarding may show exited after successful first run).

### 2) Run your first task (voice or text fallback, no curl needed)

Say the wake word and your task in one sentence:

- `Aegis, create a short 3-item plan for my workday`

If microphone is not available:
- AegisOS opens an always-on-top text input automatically.
- Type: `Create a short 3-item plan for my workday`

The assistant is always ready in background through `aegis-agent.service`, so you do not need to send manual HTTP requests.

---

## Permission prompts: what to expect

AegisOS uses policy-gated execution.

- In safer profiles, sensitive actions may be denied until approved.
- In `prompt_once`, first sensitive attempt asks/records approval per skill/action.
- After approval, repeated prompts for the same skill/action are reduced.

If a task is denied, try:
1. Re-run with a less sensitive request.
2. Change to a less restrictive permission profile.

---

## Change model size or permissions later

You can update both later without reinstalling Linux.

### Change model size/provider

Run onboarding again and pick a different model:

```bash
sudo /opt/aegisos/.venv/bin/python -m aegis.firstboot --models-dir /var/lib/aegis/models --catalog /etc/aegis/model_catalog.json --interactive --interactive-permissions --stamp /var/lib/aegis/.firstboot_done
```

### Change permission profile later

Use the same onboarding command above and select a new permission profile (`strict`, `prompt_once`, `balanced`, `open`).

---

## Automatic agent recovery

The integrated agent is configured to auto-recover:
- Service name: `aegis-agent.service`
- Restart policy: `Restart=always`
- Restart delay: `RestartSec=2`
- Restart rate limit disabled: `StartLimitIntervalSec=0`

This means if the agent crashes or is killed unexpectedly, systemd starts it again automatically.

Check restart behavior:

```bash
sudo systemctl status aegis-agent.service --no-pager
sudo journalctl -u aegis-agent.service -n 200 --no-pager
```

---

## Troubleshooting

### API is not reachable

- Ensure integrated services are running:

```bash
sudo systemctl restart aegis-api.service aegis-agent.service
```

### First-boot command fails

- Confirm onboarding service completed successfully.
- Confirm catalog exists: `/etc/aegis/model_catalog.json`
- Check service logs:

```bash
sudo journalctl -u aegis-onboarding.service -u aegis-api.service -u aegis-agent.service -n 200 --no-pager
```

### Assistant is not listening

- Confirm audio devices are available to Linux.
- Restart voice agent:

```bash
sudo systemctl restart aegis-agent.service
```

- Check voice logs:

```bash
sudo journalctl -u aegis-agent.service -n 200 --no-pager
```

- If microphone hardware is missing/unavailable, use the on-screen text input that AegisOS opens automatically and type commands directly.
- Text fallback autostart file: `/etc/xdg/autostart/aegis-text-fallback.desktop`

### Model download is slow

- This is normal for larger models.
- Pick a smaller profile first, then upgrade later.

---

## Recommended first week workflow

1. Start with `prompt_once` permission profile.
2. Use small or medium model first.
3. Run simple text tasks for day 1.
4. Move to broader permissions only after trust is established.
