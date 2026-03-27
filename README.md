# AegisOS

AegisOS is a Linux distribution integration project for a local-first AI assistant that is available immediately after first boot.

It is designed as an operating-system capability, not a standalone app: policy-gated, auditable, and managed through integrated Linux services.

## Highlights
- Integrated Linux deployment with systemd-managed onboarding, API, and always-on agent services.
- Local-first execution with no mandatory cloud dependency.
- Policy and trust controls with approval-gated sensitive actions.
- Voice-first interaction with automatic text fallback when no microphone is available.
- Packaging and image build support for distro workflows.

## Quick Start (Integrated Linux)
1. Build integrated image: ./scripts/build_iso_debian_live.sh
2. Validate evidence: ./scripts/validate_iso_evidence.sh --build
3. Install runtime in rootfs pipeline: sudo ./scripts/install_distro_rootfs.sh
4. Start services: sudo systemctl start aegis-onboarding.service aegis-api.service aegis-agent.service

## Project Structure
- aegis/: runtime code
- scripts/: install/build/ops tooling
- deploy/: systemd units and deployment assets
- tests/: unit and integration tests
- docs/: architecture and operational documentation

## Documentation
- docs/README.md
- docs/INTEGRATED_USER_FLOW.md
- docs/DISTRO_INTEGRATION.md
- docs/OPERATIONAL_RUNBOOK.md
- docs/PR_READINESS_FOR_LINUX_DISTRO.md

## License
Apache-2.0
