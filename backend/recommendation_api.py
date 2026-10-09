import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.action_api import operator
from backend.automation_api import context
from services.analytics.recommendations import DetectorConfig, SettingsConflict, read_settings, recommendations, save_settings

router = APIRouter(prefix="/api/recommendations")


@router.get("")
def listing(offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500),
            category: Literal["scale", "watch", "stop", "fatigue"] | None = None):
    from backend.app import database_sessions
    with database_sessions()() as session:
        return recommendations(session, os.environ.get("WORKSPACE_ID", "default"), offset=offset, limit=limit, category=category)


@router.get("/settings")
def settings():
    from backend.app import database_sessions
    with database_sessions()() as session:
        config, revision = read_settings(session, os.environ.get("WORKSPACE_ID", "default"))
        return {"settings": config.model_dump(mode="json"), "revision": revision}


class SettingsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: DetectorConfig
    revision: int = Field(ge=0)


@router.put("/settings")
def update_settings(command: SettingsCommand, actor_id=Depends(operator)):
    factory, workspace = context(actor_id)
    try:
        revision = save_settings(factory, workspace, command.settings, command.revision)
    except SettingsConflict as error:
        raise HTTPException(409, str(error)) from None
    return {"settings": command.settings.model_dump(mode="json"), "revision": revision}
