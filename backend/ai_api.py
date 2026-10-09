import os
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.action_api import operator
from backend.automation_api import context, conflict
from services.actions.engine import ActionEngine
from services.actions.settings import policy_from_environment
from services.ai.engine import CopilotEngine
from services.ai.policy import read_policy, save_policy
from services.ai.schema import CopilotPolicy
from services.ai.profiles import MediaProfile
from services.storage.models import AIDecision
from services.sync.engine import utc_now

router = APIRouter(prefix="/api/ai")


def engine(actor):
    factory, workspace = context(actor)
    return CopilotEngine(ActionEngine(factory, policy_from_environment())), workspace


@router.get("/settings")
def settings(actor=Depends(operator)):
    core, workspace = engine(actor)
    with core.sessions() as session:
        policy, revision = read_policy(session, workspace)
        from services.automation.control import state
        automation = state(session, workspace)
    return {"settings": policy.model_dump(mode="json"), "revision": revision, "autonomy_level": policy.autonomy_level,
        "automation": automation,
        "ai_enabled": os.environ.get("AI_ENABLED", "false").lower() == "true",
        "model": os.environ.get("OPENAI_MODEL", "") or None,
        "autopilot_allowed": os.environ.get("AI_AUTOPILOT_ALLOWED", "false").lower() == "true",
        "actions_enabled": core.actions.policy.enabled}


class SettingsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: CopilotPolicy
    revision: int = Field(ge=0)


@router.put("/settings")
def update_settings(command: SettingsCommand, actor=Depends(operator)):
    core, workspace = engine(actor)
    conflict(lambda: save_policy(core.sessions, workspace, command.settings, command.revision, utc_now()))
    return settings(actor)


class ControlCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stopped: bool
    generation: int | None = Field(default=None, ge=0)


@router.post("/automation")
def automation(command: ControlCommand, actor=Depends(operator)):
    core, workspace = engine(actor)
    from services.automation.control import change
    return conflict(lambda: change(core.sessions, workspace, actor, command.stopped, generation=command.generation))


@router.get("/automation/events")
def automation_events(actor=Depends(operator)):
    core, workspace = engine(actor)
    from services.storage.models import AutomationEvent
    with core.sessions() as session:
        rows = session.scalars(select(AutomationEvent).where(AutomationEvent.workspace_id == workspace).order_by(AutomationEvent.created_at.desc()).limit(50)).all()
        return {"events": [{"at": r.created_at.isoformat(), "actor": r.actor_id, **r.payload} for r in rows]}


class ProfileCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: MediaProfile
    revision: int = Field(ge=0)


@router.get("/profiles")
def profiles(actor=Depends(operator)):
    core, workspace = engine(actor)
    from services.storage.models import MediaBuyerProfile
    with core.sessions() as session:
        rows = session.scalars(select(MediaBuyerProfile).where(MediaBuyerProfile.workspace_id == workspace).order_by(
            MediaBuyerProfile.country, MediaBuyerProfile.offer)).all()
        return {"profiles": [{"id": r.id, "revision": r.revision, "profile": r.payload} for r in rows]}


@router.put("/profiles")
def update_profile(command: ProfileCommand, actor=Depends(operator)):
    core, workspace = engine(actor)
    from services.ai.profiles import save
    conflict(lambda: save(core.sessions, workspace, command.profile, command.revision, utc_now()))
    return profiles(actor)


class ChatCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


@router.post("/messages", status_code=202)
def chat(command: ChatCommand, actor=Depends(operator), key: str = Header(alias="Idempotency-Key")):
    core, workspace = engine(actor)
    if os.environ.get("AI_ENABLED", "false").lower() != "true" or not os.environ.get("OPENAI_MODEL"):
        raise HTTPException(409, "Configure and enable the inference worker first")
    from services.ai.agent import AgentService
    identity = conflict(lambda: AgentService(core).queue(workspace, actor, command.text, key))
    return {"message_id": identity}


@router.get("/messages")
def messages(actor=Depends(operator)):
    core, workspace = engine(actor)
    from services.ai.agent import AgentService
    from services.storage.models import AgentMessage
    with core.sessions() as session:
        rows = session.scalars(select(AgentMessage).where(AgentMessage.workspace_id == workspace,
            AgentMessage.actor_id == actor).order_by(AgentMessage.created_at.desc()).limit(30)).all()
        return {"messages": [AgentService(core).view(session, row) for row in reversed(rows)]}


class AnalyzeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_ids: list[str] = Field(min_length=1, max_length=30)


@router.post("/analyses", status_code=202)
def analyze(command: AnalyzeCommand, actor=Depends(operator), key: str = Header(alias="Idempotency-Key")):
    core, workspace = engine(actor)
    if os.environ.get("AI_ENABLED", "false").lower() != "true" or not os.environ.get("OPENAI_MODEL"):
        raise HTTPException(409, "Configure and enable the inference worker first")
    identity = conflict(lambda: core.queue(workspace, actor, command.entity_ids, key))
    return detail(identity, actor)


@router.get("/decisions")
def listing(limit: int = Query(default=30, ge=1, le=100), actor=Depends(operator)):
    core, workspace = engine(actor)
    with core.sessions() as session:
        rows = session.scalars(select(AIDecision).where(AIDecision.workspace_id == workspace).order_by(AIDecision.created_at.desc()).limit(limit)).all()
        return {"decisions": [core.view(session, row) for row in rows]}


@router.get("/decisions/{identity}")
def detail(identity: str, actor=Depends(operator)):
    core, workspace = engine(actor)
    with core.sessions() as session:
        decision = session.get(AIDecision, identity)
        if not decision or decision.workspace_id != workspace:
            raise HTTPException(404, "AI decision not found")
        return core.view(session, decision)


class ResolveCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["approve", "reject"]


@router.post("/decisions/{identity}/resolve")
def resolve(identity: str, command: ResolveCommand, actor=Depends(operator)):
    core, workspace = engine(actor)
    return conflict(lambda: core.resolve(workspace, actor, identity, command.operation))
