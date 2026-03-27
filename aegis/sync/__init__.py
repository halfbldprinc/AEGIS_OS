import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .net import P2PTransport
from ..audit import AuditLog


@dataclass
class CRDTNode:
    key: str
    value: Any
    timestamp: float


class SyncConflict(Exception):
    pass


class SyncManager:
    """Extended cross-device sync manager with CRDT, vector clocks and persistence."""

    def __init__(self, device_id: str = "local", storage_path: str | None = None):
        self.device_id = device_id
        self.state: Dict[str, CRDTNode] = {}
        self.peers: List[str] = []
        self.vector_clock: Dict[str, int] = {self.device_id: 0}
        self.storage_path = storage_path
        self.last_conflicts: List[str] = []

        if self.storage_path:
            self.load()

        # P2P transport and merge helpers
        self.transport = P2PTransport(node_id=device_id, state_provider=self.snapshot)
        self.blob_index: Dict[str, str] = {}
        self.offline_queue: List[Dict[str, Any]] = []
        self.queue_retry_limit = 3
        self.checkpoints: List[Dict[str, Any]] = []
        self.audit = AuditLog()

    def store_encrypted_blob(self, key: str, obj: Dict[str, Any]) -> str:
        blob_hash = self.transport.store_blob(key, obj)
        self.blob_index[key] = blob_hash
        if not self.peers:
            self._enqueue_offline_action("publish_blob", {"key": key, "payload": obj})
        else:
            self._publish_blob_to_peers(key, obj)
        return blob_hash

    def _publish_blob_to_peers(self, key: str, payload: Dict[str, Any]) -> bool:
        state_payload = {key: payload}
        published = self.transport.publish_state(state_payload)
        if not published:
            self._enqueue_offline_action("publish_blob", {"key": key, "payload": payload})
            return False
        return True

    def retrieve_encrypted_blob(self, key: str) -> Optional[Dict[str, Any]]:
        return self.transport.retrieve_blob(key)

    def register_peer(self, peer_id: str) -> None:
        if peer_id not in self.peers:
            self.peers.append(peer_id)

    def _increment_clock(self) -> None:
        self.vector_clock[self.device_id] = self.vector_clock.get(self.device_id, 0) + 1

    def set(self, key: str, value: Any, timestamp: float) -> None:
        self._increment_clock()
        existing = self.state.get(key)

        if existing is None or timestamp > existing.timestamp:
            self.state[key] = CRDTNode(key=key, value=value, timestamp=timestamp)
        elif timestamp == existing.timestamp and value != existing.value:
            raise SyncConflict(f"Concurrent update for key '{key}'")

        self.audit.record("sync", "set", {"device_id": self.device_id, "key": key, "timestamp": timestamp})

        if self.storage_path:
            self.save()

    def get(self, key: str) -> Any:
        node = self.state.get(key)
        return node.value if node else None

    def merge(self, other: "SyncManager" | Dict[str, Dict[str, Any]]) -> Tuple[List[str], Dict[str, Any]]:
        conflicts: List[str] = []

        if isinstance(other, SyncManager):
            other_state = other.snapshot()
            other_clock = other.vector_clock
        else:
            other_state = other
            other_clock = {}

        self._merge_vector_clock(other_clock)

        for key, incoming in other_state.items():
            inc_node_ts = incoming["timestamp"]
            inc_value = incoming["value"]
            existing = self.state.get(key)

            if existing is None or inc_node_ts > existing.timestamp:
                self.state[key] = CRDTNode(key=key, value=inc_value, timestamp=inc_node_ts)
            elif inc_node_ts == existing.timestamp and existing.value != inc_value:
                conflicts.append(key)

        self.last_conflicts = conflicts

        if self.storage_path:
            self.save()

        return conflicts, self.snapshot()

    def _merge_vector_clock(self, other_clock: Dict[str, int]) -> None:
        for peer, counter in other_clock.items():
            self.vector_clock[peer] = max(self.vector_clock.get(peer, 0), counter)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {k: {"value": v.value, "timestamp": v.timestamp} for k, v in self.state.items()}

    def save(self) -> None:
        if not self.storage_path:
            return

        payload = {
            "device_id": self.device_id,
            "vector_clock": self.vector_clock,
            "state": self.snapshot(),
            "peers": self.peers,
        }
        parent = os.path.dirname(self.storage_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        tmp_path = f"{self.storage_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.storage_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def load(self) -> None:
        if not self.storage_path or not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return

        if not isinstance(payload, dict):
            return

        self.device_id = payload.get("device_id", self.device_id)
        vector_clock = payload.get("vector_clock", self.vector_clock)
        self.vector_clock = vector_clock if isinstance(vector_clock, dict) else self.vector_clock
        peers = payload.get("peers", self.peers)
        self.peers = peers if isinstance(peers, list) else self.peers

        self.state = {}
        raw_state = payload.get("state", {})
        if not isinstance(raw_state, dict):
            return
        for key, node in raw_state.items():
            if not isinstance(node, dict):
                continue
            if "value" not in node or "timestamp" not in node:
                continue
            self.state[key] = CRDTNode(key=key, value=node["value"], timestamp=node["timestamp"])

    def merge_conflict_resolution(self, key: str, resolved_value: Any, resolved_ts: float) -> None:
        self.state[key] = CRDTNode(key=key, value=resolved_value, timestamp=resolved_ts)
        if key in self.last_conflicts:
            self.last_conflicts.remove(key)

        self.audit.record("sync", "conflict_resolved", {"key": key, "resolved_ts": resolved_ts})
        if self.storage_path:
            self.save()

    def get_conflicts(self) -> List[str]:
        return list(self.last_conflicts)

    def connect_peer(self, peer_id: str, address: str, port: int) -> bool:
        successful = self.transport.connect(peer_id, address, port)
        if successful:
            self.register_peer(peer_id)
            self.audit_connection(peer_id, "connected")
        return successful

    def disconnect_peer(self, peer_id: str) -> bool:
        successful = self.transport.disconnect(peer_id)
        if successful and peer_id in self.peers:
            self.peers.remove(peer_id)
            self.audit_connection(peer_id, "disconnected")
        return successful

    def list_peer_connections(self) -> List[str]:
        return self.transport.list_peers()

    def pull_peer_state(self, peer_id: str) -> Dict[str, Any]:
        payload = self.transport.fetch_state(peer_id)
        if payload is None:
            self._enqueue_offline_action("pull_peer_state", {"peer_id": peer_id})
            self.audit.record("sync", "peer_unavailable", {"peer_id": peer_id})
            return {"status": "unavailable", "peer": peer_id, "queued": True}

        conflicts, merged = self.merge(payload)
        self.audit.record("sync", "peer_merged", {"peer_id": peer_id, "conflicts": conflicts})
        return {"status": "merged", "peer": peer_id, "conflicts": conflicts, "merged": merged}

    def create_checkpoint(self) -> Dict[str, Any]:
        checkpoint = {
            "device_id": self.device_id,
            "vector_clock": self.vector_clock.copy(),
            "state_snapshot": self.snapshot(),
            "timestamp": time.time(),
            "checkpoint_id": secrets.token_hex(16),
        }
        self.checkpoints.append(checkpoint)
        self.audit.record("sync", "checkpoint_created", {"checkpoint_id": checkpoint["checkpoint_id"]})
        return checkpoint

    def apply_checkpoint(self, checkpoint: Dict[str, Any]) -> None:
        snapshot = checkpoint.get("state_snapshot", {})
        for key, node in snapshot.items():
            self.state[key] = CRDTNode(key=key, value=node["value"], timestamp=node["timestamp"])
        self.vector_clock.update(checkpoint.get("vector_clock", {}))
        self.audit.record("sync", "checkpoint_applied", {"checkpoint_id": checkpoint.get("checkpoint_id")})

    def publish_checkpoint(self, peer_id: str) -> bool:
        if peer_id not in self.peers:
            self.audit.record("sync", "publish_checkpoint_failed", {"peer_id": peer_id, "reason": "not_connected"})
            return False

        checkpoint = self.create_checkpoint()
        payload = {"checkpoint": checkpoint}
        success = self.transport.publish_state(payload)
        self.audit.record("sync", "checkpoint_published", {"peer_id": peer_id, "success": success})
        return success

    def _enqueue_offline_action(self, action: str, args: Dict[str, Any]) -> None:
        self.offline_queue.append({"action": action, "args": args, "attempts": 0})

    def retry_offline_queue(self) -> Dict[str, Any]:
        results = {"processed": 0, "pending": 0, "failed": 0}
        remaining = []

        for item in self.offline_queue:
            if item["attempts"] >= self.queue_retry_limit:
                results["failed"] += 1
                continue

            item["attempts"] += 1
            action = item["action"]
            args = item["args"]
            try:
                if action == "pull_peer_state":
                    outcome = self.pull_peer_state(args["peer_id"])
                    if outcome.get("status") == "merged":
                        results["processed"] += 1
                        continue
                elif action == "publish_blob":
                    if self._publish_blob_to_peers(args["key"], args["payload"]):
                        results["processed"] += 1
                        continue
                results["pending"] += 1
                remaining.append(item)
            except Exception:
                results["pending"] += 1
                remaining.append(item)

        self.offline_queue = remaining
        return results

    def audit_connection(self, peer_id: str, status: str) -> None:
        self.audit.record("sync", "peer_connection", {"device_id": self.device_id, "peer_id": peer_id, "status": status})

