"""REST API endpoint definitions for AegisOS service control."""

from contextlib import asynccontextmanager
import asyncio
from datetime import datetime
import os
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .daemon import AegisDaemon
from .evolution import EvolutionManager
from .guardian import Guardian
from .memory import MemoryStore
from .orchestrator import Plan
from .security import SecurityManager
from .logging import configure_logging

# Provide explicit lifespan hooks for startup/shutdown.
# Keep a fallback daemon instance for convenience in non-lifespan contexts.

configure_logging()
daemon = AegisDaemon()
memory_store = MemoryStore()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager to start and shutdown the daemon."""
    app.state.daemon = AegisDaemon()
    app.state.daemon.start()
    yield
    app.state.daemon.shutdown()


app = FastAPI(title="AegisOS Integrated Assistant API", version="0.1.0", lifespan=lifespan)


class OnboardingPayload(BaseModel):
    """Payload for onboarding approval endpoint."""
    approved: bool


class SoakPayload(BaseModel):
    cycles: int = Field(default=100, ge=1, le=100000)
    sleep_s: float = Field(default=0.0, ge=0.0, le=10.0)


class ChaosPayload(BaseModel):
    scenario: str = Field(min_length=1, max_length=128)


def _get_daemon():
    """Retrieve the current daemon instance from app state or fallback.global."""
    return getattr(app.state, "daemon", daemon)


def _new_sync_manager():
    from .sync import SyncManager

    return SyncManager()


def _plan_from_payload(steps: List[Dict[str, Any]]) -> Plan:
    plan = Plan()
    for step in steps:
        plan.add_step(
            skill_name=step.get("skill_name"),
            action=step.get("action"),
            params=step.get("params", {}),
        )
    return plan


@app.get("/status")
def get_status() -> dict:
    """Return a snapshot of the current daemon status."""
    return _get_daemon().get_status()


@app.post("/run-cycle")
def run_cycle() -> dict:
    """Trigger a daemon cycle and return current mode."""
    daemon_ref = _get_daemon()
    daemon_ref.run_cycle()
    return {"status": "executed", "mode": daemon_ref.state.get("mode")}


@app.post("/onboarding")
def complete_onboarding(payload: OnboardingPayload) -> dict:
    """Complete onboarding path and return adjusted mode."""
    daemon_ref = _get_daemon()
    daemon_ref.complete_onboarding(payload.approved)
    return {"mode": daemon_ref.state.get("mode")}


@app.post("/autonomy")
def enable_autonomy() -> dict:
    """Enable autonomy mode and return the active mode."""
    daemon_ref = _get_daemon()
    daemon_ref.enable_autonomy()
    return {"mode": daemon_ref.state.get("mode")}


@app.post("/v1/ops/soak")
def run_soak(payload: SoakPayload) -> dict:
    daemon_ref = _get_daemon()
    return daemon_ref.run_soak_test(cycles=payload.cycles, sleep_s=payload.sleep_s)


@app.post("/v1/ops/chaos")
def run_chaos(payload: ChaosPayload) -> dict:
    daemon_ref = _get_daemon()
    return daemon_ref.run_chaos_scenario(payload.scenario)


@app.get("/sync/status")
def get_sync_status() -> dict:
    """Return basic sync status."""
    sync_manager = _new_sync_manager()
    return {"peer_count": len(sync_manager.peers), "data_size": len(sync_manager.state)}


class PeerConnectPayload(BaseModel):
    peer_id: str = Field(min_length=1, max_length=128)
    address: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)


@app.post("/v1/sync/connect")
def connect_sync_peer(payload: PeerConnectPayload) -> dict:
    sync_manager = _new_sync_manager()
    success = sync_manager.connect_peer(payload.peer_id, payload.address, payload.port)
    return {"peer_id": payload.peer_id, "connected": success}


@app.get("/v1/sync/peers")
def list_sync_peers() -> dict:
    sync_manager = _new_sync_manager()
    return {"peers": sync_manager.list_peer_connections()}


@app.post("/v1/sync/pull")
def pull_sync_peer(payload: PeerConnectPayload) -> dict:
    sync_manager = _new_sync_manager()
    result = sync_manager.pull_peer_state(payload.peer_id)
    return result


@app.post("/v1/sync/publish")
def publish_sync_state() -> dict:
    sync_manager = _new_sync_manager()
    success = sync_manager.transport.publish_state(sync_manager.snapshot())
    return {"published": success}


@app.get("/v1/sync/conflicts")
def sync_conflicts() -> dict:
    sync_manager = _new_sync_manager()
    return {"conflicts": sync_manager.get_conflicts()}


class ConflictResolutionPayload(BaseModel):
    key: str = Field(min_length=1, max_length=256)
    resolved_value: Any
    resolved_ts: float


@app.post("/v1/sync/conflict")
def resolve_sync_conflict(payload: ConflictResolutionPayload) -> dict:
    sync_manager = _new_sync_manager()
    sync_manager.merge_conflict_resolution(payload.key, payload.resolved_value, payload.resolved_ts)
    return {"status": "resolved", "key": payload.key, "resolved": True}


@app.get("/v1/resource/status")
def get_resource_status() -> dict:
    daemon_ref = _get_daemon()
    decision = daemon_ref.resource_scheduler.schedule_yield()
    return {"resource_decision": decision}


@app.get("/v1/resources")
def get_resources() -> dict:
    daemon_ref = _get_daemon()
    return daemon_ref.resource_scheduler.get_metrics()


@app.get("/v1/metrics")
def get_system_metrics() -> dict:
    daemon_ref = _get_daemon()
    resource_metrics = daemon_ref.resource_scheduler.get_metrics()
    trust_snapshot = daemon_ref.trust_ledger.export()
    return {
        "resource_metrics": resource_metrics,
        "daemon_telemetry": daemon_ref.get_telemetry(),
        "trust_snapshot": {k: v.__dict__ for k, v in trust_snapshot.items()},
        "mode": daemon_ref.state.get("mode"),
    }


@app.get("/v1/metrics/prometheus")
def get_prometheus_metrics() -> str:
    daemon_ref = _get_daemon()
    return daemon_ref.resource_scheduler.get_prometheus_metrics()


@app.get("/v1/metrics/telemetry")
def get_telemetry_metrics() -> str:
    daemon_ref = _get_daemon()
    return daemon_ref.telemetry_manager.exporter_text()


@app.websocket("/v1/ws/plan-events")
async def websocket_plan_events(websocket: WebSocket):
    await websocket.accept()
    daemon_ref = _get_daemon()
    read_offset = 0
    max_events_per_tick = max(1, int(os.getenv("AEGIS_WS_PLAN_EVENTS_BATCH", "1000")))
    try:
        while True:
            events, read_offset = daemon_ref.audit_log.read_from_offset(read_offset, max_events=max_events_per_tick)
            for event in events:
                await websocket.send_json(
                    {
                        "timestamp": event.timestamp,
                        "source": event.source,
                        "event_type": event.event_type,
                        "details": event.details,
                    }
                )
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


class PermissionPayload(BaseModel):
    """Payload for setting or removing skill permissions."""
    skill_name: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    duration_hours: int | None = Field(default=None, ge=1, le=720)


@app.get("/v1/trust")
def get_trust_snapshot() -> dict:
    daemon_ref = _get_daemon()
    raw = daemon_ref.trust_ledger.export()
    return {k: v.__dict__ for k, v in raw.items()}


@app.get("/v1/memory/search")
def search_memory(q: str = Query(..., min_length=1), top_k: int = Query(5, ge=1, le=50)) -> dict:
    results = memory_store.search(q, top_k=top_k)
    return {"query": q, "results": results}


class MemoryUpsertPayload(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    metadata: Optional[Dict[str, Any]] = None


@app.post("/v1/memory/upsert")
def upsert_memory(payload: MemoryUpsertPayload) -> dict:
    entry = memory_store.upsert(payload.text, payload.metadata or {})
    return {
        "id": entry.id,
        "text": entry.text,
        "metadata": entry.metadata,
        "created_at": datetime.fromtimestamp(entry.created_at).isoformat(),
    }


@app.delete("/v1/memory/{entry_id}")
def delete_memory(entry_id: str) -> dict:
    success = memory_store.delete(entry_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {"deleted": True, "id": entry_id}


@app.get("/v1/memory/{entry_id}")
def get_memory(entry_id: str) -> dict:
    entry = memory_store.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {
        "id": entry.id,
        "text": entry.text,
        "metadata": entry.metadata,
        "created_at": datetime.fromtimestamp(entry.created_at).isoformat(),
    }


@app.post("/v1/guardian/grant")
def grant_permission(payload: PermissionPayload) -> dict:
    daemon_ref = _get_daemon()
    guardian = daemon_ref.orchestrator.guardian
    if not isinstance(guardian, Guardian):
        raise HTTPException(status_code=500, detail="Guardian is not available")
    guardian.grant(payload.skill_name, payload.action, payload.duration_hours)
    return {"status": "granted", "skill_name": payload.skill_name, "action": payload.action}


@app.post("/v1/guardian/revoke")
def revoke_permission(payload: PermissionPayload) -> dict:
    daemon_ref = _get_daemon()
    guardian = daemon_ref.orchestrator.guardian
    if not isinstance(guardian, Guardian):
        raise HTTPException(status_code=500, detail="Guardian is not available")
    guardian.revoke(payload.skill_name, payload.action)
    return {"status": "revoked", "skill_name": payload.skill_name, "action": payload.action}


@app.get("/v1/guardian")
def list_permissions() -> dict:
    daemon_ref = _get_daemon()
    guardian = daemon_ref.orchestrator.guardian
    if not isinstance(guardian, Guardian):
        raise HTTPException(status_code=500, detail="Guardian is not available")
    return {"permissions": guardian.list_permissions()}


@app.get("/v1/guardian/check")
def check_permission(skill_name: str, action: str) -> dict:
    daemon_ref = _get_daemon()
    guardian = daemon_ref.orchestrator.guardian
    if not isinstance(guardian, Guardian):
        raise HTTPException(status_code=500, detail="Guardian is not available")
    allowed = guardian.check(skill_name, action)
    return {"skill_name": skill_name, "action": action, "allowed": allowed}


class SimulatePlanPayload(BaseModel):
    steps: List[Dict[str, Any]]


@app.post("/v1/orchestrator/simulate")
def simulate_plan(payload: SimulatePlanPayload) -> dict:
    daemon_ref = _get_daemon()
    plan = _plan_from_payload(payload.steps)
    return daemon_ref.orchestrator.simulate_plan(plan)


@app.post("/v1/orchestrator/preview")
def preview_plan(payload: SimulatePlanPayload) -> dict:
    daemon_ref = _get_daemon()
    plan = _plan_from_payload(payload.steps)
    return daemon_ref.orchestrator.simulate_plan(plan)


class ProcessPayload(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


class ProcessAndExecutePayload(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    allow_failure: bool = False


class ConfirmPayload(BaseModel):
    plan_id: str = Field(min_length=1, max_length=128)
    step_id: str = Field(min_length=1, max_length=128)
    approved: bool


class VoiceTextPayload(BaseModel):
    transcript: str = Field(max_length=50000)


class VoiceAudioPayload(BaseModel):
    audio_path: str = Field(min_length=1, max_length=4096)


class FeedbackPayload(BaseModel):
    turn_id: str = Field(min_length=1, max_length=128)
    satisfaction: int = Field(ge=1, le=5)


@app.post("/v1/process")
def process_instruction(payload: ProcessPayload) -> dict:
    daemon_ref = _get_daemon()
    plan = daemon_ref.create_plan_from_instruction(payload.text)
    return {"plan_id": plan.id, "status": plan.status, "steps": [{"id": s.id, "skill": s.skill_name, "action": s.action, "params": s.params} for s in plan.steps]}


@app.post("/v1/process-and-execute")
def process_and_execute(payload: ProcessAndExecutePayload) -> dict:
    daemon_ref = _get_daemon()
    plan = daemon_ref.create_plan_from_instruction(payload.text)
    return daemon_ref.execute_plan_by_id(plan.id, allow_failure=payload.allow_failure)


@app.post("/v1/execute/{plan_id}")
def execute_plan(plan_id: str, allow_failure: bool = False) -> dict:
    daemon_ref = _get_daemon()
    try:
        return daemon_ref.execute_plan_by_id(plan_id, allow_failure=allow_failure)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/v1/plan/{plan_id}")
def get_plan(plan_id: str) -> dict:
    daemon_ref = _get_daemon()
    plan = daemon_ref.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {
        "plan_id": plan.id,
        "status": plan.status,
        "steps": [{"id": s.id, "skill": s.skill_name, "action": s.action, "status": s.status, "result": s.result.data if s.result else None} for s in plan.steps],
    }


@app.post("/v1/confirm")
def confirm_plan(payload: ConfirmPayload) -> dict:
    daemon_ref = _get_daemon()
    try:
        plan = daemon_ref.confirm_plan_step(payload.plan_id, payload.step_id, payload.approved)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"plan_id": plan.id, "status": plan.status, "steps": [{"id": s.id, "status": s.status, "result": s.result.data if s.result else None} for s in plan.steps]}


@app.post("/v1/voice/process-text")
def process_voice_text(payload: VoiceTextPayload) -> dict:
    daemon_ref = _get_daemon()
    transcript = payload.transcript.strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="'transcript' must not be empty")
    return daemon_ref.process_voice_text(transcript)


@app.post("/v1/voice/process-audio")
def process_voice_audio(payload: VoiceAudioPayload) -> dict:
    daemon_ref = _get_daemon()
    try:
        return daemon_ref.process_voice_audio(payload.audio_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/v1/feedback/rate")
def rate_conversation_turn(payload: FeedbackPayload) -> dict:
    """Rate a conversation turn for satisfaction feedback (1-5 scale)."""
    daemon_ref = _get_daemon()
    try:
        turn_id = payload.turn_id
        satisfaction = payload.satisfaction
        
        if not turn_id:
            raise HTTPException(status_code=400, detail="'turn_id' required")
        if satisfaction is None or not (1 <= satisfaction <= 5):
            raise HTTPException(status_code=400, detail="'satisfaction' must be 1-5")
        
        success = daemon_ref.conversation_manager.rate_turn(turn_id, satisfaction)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to rate turn")
        
        return {"success": True, "turn_id": turn_id, "satisfaction": satisfaction}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/conversation/history")
def get_conversation_history(session_id: str) -> dict:
    """Retrieve all turns from a conversation session."""
    daemon_ref = _get_daemon()
    try:
        if not session_id:
            raise HTTPException(status_code=400, detail="'session_id' query parameter required")
        
        turns = daemon_ref.conversation_manager.get_session_history(session_id)
        return {"session_id": session_id, "turns": [t.__dict__ for t in turns], "total_turns": len(turns)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/ui/status")
def ui_status() -> dict:
    daemon_ref = _get_daemon()
    return {
        "mode": daemon_ref.state.get("mode"),
        "startup": daemon_ref.state.get("startup", True),
        "registered_skills": daemon_ref.orchestrator.list_skills(),
        "voice_monitor_running": getattr(daemon_ref, "_voice_monitor_thread", None) is not None,
    }


@app.get("/v1/conversation/sessions")
def list_sessions() -> dict:
    daemon_ref = _get_daemon()
    return {"sessions": daemon_ref.conversation_manager.list_sessions()}


@app.get("/v1/conversation/stats")
def get_conversation_stats(session_id: str | None = None) -> dict:
    """Get satisfaction statistics for conversation turns."""
    daemon_ref = _get_daemon()
    try:
        stats = daemon_ref.conversation_manager.get_satisfaction_stats(session_id)
        return {
            "session_id": session_id,
            **stats,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/v1/evolution/approve")
def approve_evolution(proposal_id: str) -> dict:
    proposal = evolution_manager.approve_proposal(proposal_id)
    return {"proposal_id": proposal.proposal_id, "approved": proposal.approved}


security_manager = SecurityManager()

evolution_manager = EvolutionManager()


@app.get("/v1/security/status")
def get_security_status() -> dict:
    return security_manager.status()


@app.get("/v1/security/health")
def get_security_health() -> dict:
    return security_manager.health_status()


class LuksPayload(BaseModel):
    device: str
    passphrase: Optional[str] = None


@app.post("/v1/security/luks")
def create_luks_volume(payload: LuksPayload) -> dict:
    record = security_manager.prepare_luks_volume(payload.device, payload.passphrase)
    return record


class FscryptPayload(BaseModel):
    path: str


@app.post("/v1/security/fscrypt")
def create_fscrypt_path(payload: FscryptPayload) -> dict:
    record = security_manager.prepare_fscrypt_path(payload.path)
    return record


@app.post("/v1/security/secret/{key_id}/rotate")
def rotate_security_secret(key_id: str) -> dict:
    record = security_manager.secret_manager.rotate_secret(key_id)
    return {"key_id": key_id, "expires_at": record.expires_at.isoformat()}


@app.post("/v1/security/selinux")
def apply_selinux_policy(policy: dict) -> dict:
    rules = policy.get("rules", "")
    security_manager.selinux_manager.apply_policy(rules)
    return {"status": "applied", "policy_path": security_manager.selinux_manager.policy_path}


@app.get("/v1/security/selinux/validate")
def validate_selinux_policy() -> dict:
    valid = security_manager.selinux_manager.validate_policy()
    return {"valid": valid}


@app.post("/v1/security/audit/backup")
def backup_audit_log(destination: str) -> dict:
    result = security_manager.backup_audit_log(destination)
    return result


@app.post("/v1/security/audit/retention")
def enforce_audit_retention(age_days: int = 30) -> dict:
    return security_manager.enforce_audit_retention(age_days=age_days)


class AppArmorPayload(BaseModel):
    profile_name: str
    rules: str


@app.post("/v1/security/apparmor")
def apply_apparmor(payload: AppArmorPayload) -> dict:
    return security_manager.apply_apparmor_profile(payload.profile_name, payload.rules)


class ImmutablePayload(BaseModel):
    destination: str


@app.post("/v1/security/immutable")
def register_immutable_store(payload: ImmutablePayload) -> dict:
    return security_manager.immutability_target(payload.destination)


@app.get("/evolution/proposals")
def list_evolution_proposals() -> dict:
    """List pending and historical evolution proposals."""
    proposals = evolution_manager.list_proposals()
    return {"proposals": [p.__dict__ for p in proposals]}


@app.post("/evolution/proposals")
def create_evolution_proposal(payload: dict) -> dict:
    """Create a new evolution proposal telemetry entry."""
    proposal = evolution_manager.create_proposal(payload.get("proposal_id"), payload.get("metrics", {}))
    return {"proposal": proposal.__dict__}


@app.post("/evolution/proposals/{proposal_id}/approve")
def approve_evolution_proposal(proposal_id: str) -> dict:
    proposal = evolution_manager.approve_proposal(proposal_id)
    return {"proposal": proposal.__dict__}


@app.post("/evolution/proposals/{proposal_id}/apply")
def apply_evolution_proposal(proposal_id: str) -> dict:
    proposal = evolution_manager.apply_proposal(proposal_id)
    return {"proposal": proposal.__dict__}


@app.post("/evolution/proposals/{proposal_id}/execute")
def execute_evolution_proposal(proposal_id: str, canary_percentage: float = 100.0, audit_signoff: bool = False) -> dict:
    proposal = evolution_manager.execute_proposal(proposal_id, canary_percentage=canary_percentage, audit_signoff=audit_signoff)
    return {"proposal": proposal.__dict__}
