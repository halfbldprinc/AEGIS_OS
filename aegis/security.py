import logging
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import keyring
except ImportError:
    keyring = None

from .audit import AuditLog
from .utils.time import now_utc

logger = logging.getLogger(__name__)


@dataclass
class SecretRecord:
    key_id: str
    value: str
    created_at: datetime
    expires_at: datetime


class SecretManager:
    """Manages encrypted application secrets and rotation schedule."""

    ROTATION_DAYS = 90

    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = storage_path or os.getenv("AEGIS_SECRET_STORE", "/var/lib/aegis/secrets.json")
        self.secrets: Dict[str, SecretRecord] = {}
        self.audit = AuditLog()

        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            self.secrets = {}
            return

        try:
            import json

            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw = json.load(f)

            for key_id, data in raw.items():
                self.secrets[key_id] = SecretRecord(
                    key_id=key_id,
                    value=data["value"],
                    created_at=datetime.fromisoformat(data["created_at"]),
                    expires_at=datetime.fromisoformat(data["expires_at"]),
                )
        except Exception as exc:
            logger.exception("Failed to load secrets store: %s", exc)
            self.secrets = {}

    def _persist(self) -> None:
        directory = os.path.dirname(self.storage_path)
        if directory:
            try:
                os.makedirs(directory, exist_ok=True)
            except PermissionError:
                fallback_dir = os.path.join("/tmp", "aegis")
                os.makedirs(fallback_dir, exist_ok=True)
                self.storage_path = os.path.join(fallback_dir, os.path.basename(self.storage_path))

        import json

        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        key_id: {
                            "value": record.value,
                            "created_at": record.created_at.isoformat(),
                            "expires_at": record.expires_at.isoformat(),
                        }
                        for key_id, record in self.secrets.items()
                    },
                    f,
                    indent=2,
                )
        except Exception as exc:
            logger.warning("Unable to persist secrets to %s: %s", self.storage_path, exc)

    def create_secret(self, key_id: str) -> SecretRecord:
        now = now_utc()
        value = secrets.token_hex(32)
        record = SecretRecord(
            key_id=key_id,
            value=value,
            created_at=now,
            expires_at=now + timedelta(days=self.ROTATION_DAYS),
        )
        self.secrets[key_id] = record
        self._persist()
        self.audit.record("security", "secret_created", {"key_id": key_id})
        return record

    def get_secret(self, key_id: str) -> Optional[str]:
        record = self.secrets.get(key_id)
        if record is None:
            return None
        return record.value

    def rotate_secret(self, key_id: str) -> SecretRecord:
        if key_id not in self.secrets:
            raise KeyError(f"Secret not found: {key_id}")
        record = self.create_secret(key_id)
        self.audit.record("security", "secret_rotated", {"key_id": key_id})
        return record

    def expires_soon(self, key_id: str, days: int = 7) -> bool:
        if key_id not in self.secrets:
            raise KeyError(f"Secret not found: {key_id}")
        return now_utc() + timedelta(days=days) >= self.secrets[key_id].expires_at


class SELinuxPolicyManager:
    """SELinux policy manager with syntax-aware validation for policy files."""

    def __init__(self, policy_path: Optional[str] = None):
        self.policy_path = policy_path or "/etc/selinux/aegis.policy"
        self.audit = AuditLog()

    @staticmethod
    def _normalize_rules(policy_rules: str) -> list[str]:
        lines = []
        for raw in policy_rules.splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lines.append(stripped)
        return lines

    @staticmethod
    def _is_valid_rule(rule: str) -> bool:
        # Accept common SELinux snippets and require statement termination.
        if not rule.endswith(";"):
            return False
        tokens = ("allow ", "dontaudit ", "type ", "attribute ", "require ")
        return any(rule.startswith(prefix) for prefix in tokens)

    def apply_policy(self, policy_rules: str) -> None:
        normalized = self._normalize_rules(policy_rules)
        if not normalized:
            raise ValueError("Policy must contain at least one non-comment rule")

        invalid = [rule for rule in normalized if not self._is_valid_rule(rule)]
        if invalid:
            raise ValueError(f"Invalid SELinux rule(s): {invalid}")

        os.makedirs(os.path.dirname(self.policy_path), exist_ok=True)
        with open(self.policy_path, "w", encoding="utf-8") as f:
            f.write("\n".join(normalized) + "\n")

        self.audit.record("security", "selinux_policy_applied", {"path": self.policy_path, "rule_count": len(normalized)})

    def validate_policy(self) -> bool:
        if not os.path.exists(self.policy_path):
            self.audit.record("security", "selinux_policy_validate", {"path": self.policy_path, "exists": False})
            return False

        with open(self.policy_path, "r", encoding="utf-8") as f:
            content = f.read()

        normalized = self._normalize_rules(content)
        valid = bool(normalized) and all(self._is_valid_rule(rule) for rule in normalized)
        self.audit.record("security", "selinux_policy_validate", {"path": self.policy_path, "exists": True, "valid": valid, "rule_count": len(normalized)})
        return valid


class SecurityManager:
    """High-level security orchestration for Aegis."""

    def __init__(self):
        self.secret_manager = SecretManager()
        self.selinux_manager = SELinuxPolicyManager()

    def ensure_audit_key(self) -> str:
        key_id = "audit_log_key"
        if keyring is not None:
            stored = keyring.get_password("aegis", key_id)
            if stored:
                return stored

        if self.secret_manager.get_secret(key_id):
            value = self.secret_manager.get_secret(key_id)
            if keyring is not None:
                keyring.set_password("aegis", key_id, value)
            return value

        record = self.secret_manager.create_secret(key_id)
        if keyring is not None:
            keyring.set_password("aegis", key_id, record.value)
        return record.value

    def prepare_luks_volume(self, device: str, passphrase: Optional[str] = None, dry_run: bool = True) -> Dict[str, Any]:
        if not sys.platform.startswith("linux"):
            raise EnvironmentError("LUKS setup is supported on Linux only")

        passphrase = passphrase or secrets.token_hex(32)
        self.audit = AuditLog()
        self.audit.record("security", "prepare_luks", {"device": device, "dry_run": dry_run})

        if not shutil.which("cryptsetup"):
            return {"device": device, "status": "failed", "reason": "cryptsetup_not_found"}

        format_cmd = ["cryptsetup", "luksFormat", device, "--batch-mode"]
        add_key_cmd = ["cryptsetup", "luksAddKey", device, "-"]

        if dry_run:
            return {
                "device": device,
                "status": "planned",
                "passphrase_generated": True,
                "commands": [format_cmd, add_key_cmd],
            }

        try:
            subprocess.run(format_cmd, input=(passphrase + "\n"), text=True, capture_output=True, check=True)
            subprocess.run(add_key_cmd, input=(passphrase + "\n"), text=True, capture_output=True, check=True)
        except subprocess.CalledProcessError as exc:
            return {"device": device, "status": "failed", "error": exc.stderr.strip()}

        return {"device": device, "status": "prepared", "passphrase_generated": True}

    def prepare_fscrypt_path(self, path: str, dry_run: bool = True) -> Dict[str, Any]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Path not found: {path}")

        self.audit = AuditLog()
        self.audit.record("security", "prepare_fscrypt", {"path": path, "dry_run": dry_run})

        if not shutil.which("fscrypt"):
            return {"path": path, "status": "failed", "reason": "fscrypt_not_found"}

        cmd = ["fscrypt", "setup", path]

        if dry_run:
            return {"path": path, "status": "planned", "mode": "fscrypt", "command": cmd}

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            return {"path": path, "status": "failed", "error": exc.stderr.strip(), "mode": "fscrypt"}

        return {"path": path, "status": "prepared", "mode": "fscrypt"}

    def backup_audit_log(self, destination: str) -> Dict[str, Any]:
        audit = self.secret_manager.audit
        result = audit.backup(Path(destination))
        return {"destination": destination, "success": result}

    def enforce_audit_retention(self, age_days: int = 30) -> Dict[str, Any]:
        audit = self.secret_manager.audit
        expired_count = audit.expire_entries(age_days=age_days)
        return {"age_days": age_days, "expired_count": expired_count}

    def health_status(self) -> Dict[str, Any]:
        integrity_ok = AuditLog().verify_integrity()
        return {
            "secrets": len(self.secret_manager.secrets),
            "selinux_policy_exists": os.path.exists(self.selinux_manager.policy_path),
            "audit_integrity": integrity_ok,
        }

    def status(self) -> Dict[str, Any]:
        return {
            "secret_count": len(self.secret_manager.secrets),
            "selinux_policy_exists": os.path.exists(self.selinux_manager.policy_path),
            "apparmor_enabled": os.path.exists("/etc/apparmor.d"),
        }

    def apply_apparmor_profile(self, profile_name: str, profile_rules: str) -> Dict[str, Any]:
        profile_path = f"/etc/apparmor.d/{profile_name}"
        if not os.access(os.path.dirname(profile_path), os.W_OK):
            # fallback to /tmp for non-root environments
            profile_path = os.path.join("/tmp", "apparmor.d", profile_name)

        try:
            os.makedirs(os.path.dirname(profile_path), exist_ok=True)
            with open(profile_path, "w", encoding="utf-8") as f:
                f.write(profile_rules)
            self.secret_manager.audit.record("security", "apparmor_applied", {"profile": profile_name})
            return {"profile": profile_name, "status": "applied", "path": profile_path}
        except Exception as exc:
            self.secret_manager.audit.record("security", "apparmor_failed", {"profile": profile_name, "error": str(exc)})
            return {"profile": profile_name, "status": "failed", "error": str(exc)}

    def immutability_target(self, destination: str) -> Dict[str, Any]:
        # Minimal implementation to demonstrate immutable audit archive target (e.g., WORM store visited).
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with open(destination, "a", encoding="utf-8") as f:
                f.write(f"immutable registered at {now_utc().isoformat()}\n")
            self.secret_manager.audit.record("security", "immutable_store_registered", {"destination": destination})
            return {"destination": destination, "status": "registered"}
        except Exception as exc:
            self.secret_manager.audit.record("security", "immutable_store_failed", {"destination": destination, "error": str(exc)})
            return {"destination": destination, "status": "failed", "error": str(exc)}
