import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import blake3
except ImportError:
    blake3 = None

try:
    import noise.protocol as noise_protocol
except ImportError:
    noise_protocol = None

logger = logging.getLogger(__name__)


@dataclass
class PeerRecord:
    peer_id: str
    address: str
    port: int
    auth_token: str


class P2PTransport:
    """Peer transport abstraction with deterministic in-process exchange.

    This transport is intentionally local-first for reproducible tests and
    offline development. Each instance registers an endpoint and can exchange
    envelopes with other registered peers.
    """

    MAX_RETRY = 3
    REPLAY_WINDOW_SIZE = 128
    _MESH_REGISTRY: Dict[Tuple[str, int], "P2PTransport"] = {}
    _MESH_LOCK = Lock()
    _EPHEMERAL_PORT = 40000

    def __init__(
        self,
        node_id: str = "local-node",
        bind_address: str = "127.0.0.1",
        bind_port: int = 0,
        state_provider: Optional[Callable[[], Dict[str, Dict[str, Any]]]] = None,
        auth_token: Optional[str] = None,
        enforce_peer_auth: bool = True,
    ):
        self.node_id = node_id
        self.connected_peers: List[str] = []
        self.peer_records: Dict[str, PeerRecord] = {}
        self.encrypted_store: Dict[str, str] = {}
        self.retry_attempts: Dict[str, int] = {}
        self.sent_messages: List[Dict[str, Any]] = []
        self.state_provider = state_provider
        self.auth_token = auth_token or secrets.token_hex(32)
        self.enforce_peer_auth = enforce_peer_auth
        self.trusted_peer_tokens: Dict[str, str] = {}

        self.session_key = self._generate_session_key()
        self.replay_window: List[str] = []

        self.bind_address = bind_address
        self.bind_port = bind_port or self._reserve_port()
        self._register_endpoint()

    @classmethod
    def _reserve_port(cls) -> int:
        with cls._MESH_LOCK:
            cls._EPHEMERAL_PORT += 1
            return cls._EPHEMERAL_PORT

    def _register_endpoint(self) -> None:
        endpoint = (self.bind_address, self.bind_port)
        with self._MESH_LOCK:
            self._MESH_REGISTRY[endpoint] = self

    @classmethod
    def _lookup_peer(cls, address: str, port: int) -> Optional["P2PTransport"]:
        with cls._MESH_LOCK:
            return cls._MESH_REGISTRY.get((address, port))

    @staticmethod
    def _hash_blob(data: str) -> str:
        if blake3 is not None:
            return blake3.blake3(data.encode("utf-8")).hexdigest()
        return hashlib.blake2b(data.encode("utf-8"), digest_size=32).hexdigest()

    def _generate_session_key(self) -> str:
        # Creates a pseudo-random session key for encrypted communications.
        return secrets.token_hex(32)

    def _validate_replay(self, message_id: str) -> bool:
        if message_id in self.replay_window:
            return False
        self.replay_window.append(message_id)
        self.replay_window = self.replay_window[-self.REPLAY_WINDOW_SIZE :]
        return True

    @staticmethod
    def _is_valid_peer_endpoint(peer_id: str, address: str, port: int) -> bool:
        if not peer_id or not isinstance(peer_id, str):
            return False
        if not address or not isinstance(address, str):
            return False
        if not isinstance(port, int):
            return False
        if port <= 0 or port > 65535:
            return False
        return True

    def store_blob(self, key: str, obj: Dict[str, Any]) -> str:
        payload = json.dumps(obj, sort_keys=True, separators=(",", ":"))
        blob_key = self._hash_blob(payload)
        self.encrypted_store[key] = payload
        self.sent_messages.append({"id": secrets.token_hex(16), "key": key, "hash": blob_key, "timestamp": int(time.time())})
        return blob_key

    def retrieve_blob(self, key: str) -> Optional[Dict[str, Any]]:
        payload = self.encrypted_store.get(key)
        if payload is None:
            return None
        return json.loads(payload)

    def connect(self, peer_id: str, address: str, port: int, auth_token: Optional[str] = None) -> bool:
        if not self._is_valid_peer_endpoint(peer_id, address, port):
            logger.warning("Invalid peer endpoint for connect: peer_id=%r address=%r port=%r", peer_id, address, port)
            return False

        if peer_id in self.connected_peers:
            logger.debug("Peer %s already connected", peer_id)
            return True

        logger.info("Connecting to peer %s at %s:%d", peer_id, address, port)

        peer = self._lookup_peer(address, port)
        negotiated_token = auth_token
        if peer is not None:
            if peer.node_id != peer_id:
                logger.warning("Peer id mismatch: expected=%s actual=%s", peer_id, peer.node_id)
                return False
            negotiated_token = negotiated_token or peer.auth_token

            if self.enforce_peer_auth:
                if not negotiated_token or not hmac.compare_digest(negotiated_token, peer.auth_token):
                    logger.warning("Peer authentication failed for %s", peer_id)
                    return False
                self.trusted_peer_tokens[peer_id] = peer.auth_token
                peer.trusted_peer_tokens[self.node_id] = self.auth_token

        if negotiated_token is None:
            negotiated_token = secrets.token_hex(32)

        self.peer_records[peer_id] = PeerRecord(peer_id=peer_id, address=address, port=port, auth_token=negotiated_token)
        self.connected_peers.append(peer_id)
        return True

    def disconnect(self, peer_id: str) -> bool:
        if peer_id not in self.connected_peers:
            logger.debug("Peer %s not connected", peer_id)
            return False

        logger.info("Disconnecting peer %s", peer_id)
        self.connected_peers.remove(peer_id)
        self.peer_records.pop(peer_id, None)
        self.trusted_peer_tokens.pop(peer_id, None)
        return True

    def list_peers(self) -> List[str]:
        return list(self.connected_peers)

    def publish_state(self, state_payload: Dict[str, Dict[str, object]]) -> bool:
        if not self.connected_peers:
            logger.warning("No connected peers available, cannot publish state")
            return False

        logger.info("Publishing state to peers: %s", list(self.connected_peers))
        delivered = 0

        for peer_id in self.connected_peers:
            if self._send_envelope(peer_id=peer_id, message_type="state_update", payload=state_payload):
                delivered += 1

        return delivered > 0

    def _build_envelope(self, peer_id: str, message_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "id": secrets.token_hex(16),
            "sender": self.node_id,
            "target": peer_id,
            "type": message_type,
            "timestamp": time.time(),
            "payload": payload,
        }
        serialized = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self.auth_token.encode("utf-8"), serialized, hashlib.sha256).hexdigest()
        body["sig"] = signature
        return body

    def _verify_envelope_signature(self, envelope: Dict[str, Any]) -> bool:
        sender = envelope.get("sender")
        if not sender:
            return False

        sender_token = self.trusted_peer_tokens.get(sender)
        if sender_token is None:
            if self.enforce_peer_auth:
                return False
            record = self.peer_records.get(sender)
            sender_token = record.auth_token if record else None
            if sender_token is None:
                return False

        sig = envelope.get("sig")
        if not isinstance(sig, str) or not sig:
            return False

        unsigned = {k: v for k, v in envelope.items() if k != "sig"}
        serialized = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = hmac.new(sender_token.encode("utf-8"), serialized, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)

    def _send_envelope(self, peer_id: str, message_type: str, payload: Dict[str, Any]) -> bool:
        record = self.peer_records.get(peer_id)
        if record is None:
            logger.warning("Cannot send to unknown peer %s", peer_id)
            return False

        peer = self._lookup_peer(record.address, record.port)
        if peer is None:
            logger.warning("Peer endpoint %s:%d not available", record.address, record.port)
            return False

        envelope = self._build_envelope(peer_id=peer_id, message_type=message_type, payload=payload)
        return peer._receive_envelope(envelope)

    def _receive_envelope(self, envelope: Dict[str, Any]) -> bool:
        message_id = envelope.get("id")
        if not message_id or not self._validate_replay(message_id):
            return False

        if not self._verify_envelope_signature(envelope):
            logger.warning("Rejected envelope with invalid signature from %s", envelope.get("sender"))
            return False

        message_type = envelope.get("type")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            return False

        if message_type == "state_update":
            self.store_blob(f"state:{envelope.get('sender', 'unknown')}", payload)
            return True

        return True

    def fetch_state(self, peer_id: str) -> Optional[Dict[str, Dict[str, object]]]:
        logger.info("Fetching state from peer %s", peer_id)
        if peer_id not in self.connected_peers:
            logger.warning("Peer %s is not connected", peer_id)
            return None

        self.retry_attempts[peer_id] = self.retry_attempts.get(peer_id, 0) + 1
        if self.retry_attempts[peer_id] > self.MAX_RETRY:
            logger.warning("Max retry exceeded for peer %s", peer_id)
            return None

        record = self.peer_records.get(peer_id)
        if record is None:
            return None

        if self.enforce_peer_auth and peer_id not in self.trusted_peer_tokens:
            logger.warning("State fetch denied for unauthenticated peer %s", peer_id)
            return None

        peer = self._lookup_peer(record.address, record.port)
        if peer is None:
            return None

        state = peer._provide_state()
        if state is None:
            return None
        return state

    def _provide_state(self) -> Optional[Dict[str, Dict[str, object]]]:
        if self.state_provider is None:
            return None
        return self.state_provider()
