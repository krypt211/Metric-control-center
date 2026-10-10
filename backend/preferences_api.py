"""Only private UI settings are writable in advertising READ-only mode."""
from datetime import datetime,timezone
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter,Request,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field,StrictInt,model_validator
from sqlalchemy import select,update,delete,text
from backend.auth import identity,factory
from services.preferences.registry import validate_config,normalize_config,system_presets
from services.storage.models import UserColumnPreset,UserTablePreference

router=APIRouter()
Scope=Literal["account","campaign","adset","ad","creative","tracker","eco_account","eco_campaign","eco_adset","eco_ad","rule_ad","manual_ad"]
BASE="/api/preferences/columns"
def now():return datetime.now(timezone.utc)
class StrictModel(BaseModel):
    model_config=ConfigDict(extra="forbid")
class Column(StrictModel):
    key:str=Field(min_length=1,max_length=64)
    width:StrictInt
class Sorting(StrictModel):
    key:str=Field(min_length=1,max_length=64)
    direction:Literal["asc","desc"]
class Config(StrictModel):
    version:Literal[1]=1
    columns:list[Column]=Field(min_length=1,max_length=100)
    widths:dict[str,StrictInt]=Field(default_factory=dict,max_length=100)
    sorting:Sorting|None=None
class Create(StrictModel):
    scope:Scope
    name:str=Field(min_length=1,max_length=80)
    config:Config
    preference_version:StrictInt=Field(ge=0)
class Edit(StrictModel):
    name:str=Field(min_length=1,max_length=80)
    config:Config
    version:StrictInt=Field(ge=1)
    preference_version:StrictInt=Field(ge=0)
class View(StrictModel):
    active_id:str=Field(min_length=1,max_length=64)
    config:Config
    version:StrictInt=Field(ge=0)
class Choose(StrictModel):
    preset_id:str=Field(min_length=1,max_length=64)
    version:StrictInt=Field(ge=0)

def name(value):
    value=value.strip()
    if not value or any(ord(c)<32 or ord(c)==127 for c in value):raise HTTPException(422,"INVALID_PRESET_NAME")
    return value
def config(value,scope):
    try:return validate_config(value.model_dump(),scope)
    except ValueError as e:raise HTTPException(422,str(e)) from None
def own(s,actor,key):
    row=s.scalar(select(UserColumnPreset).where(UserColumnPreset.id==key,
        UserColumnPreset.user_id==actor["id"],UserColumnPreset.workspace_id==actor["workspace"]))
    if not row:raise HTTPException(404,"PRESET_NOT_FOUND")
    return row
def preset_json(row):
    return {"id":row.id,"name":row.name,"scope":row.scope,"system":False,"config":normalize_config(row.config_json,row.scope),
        "version":row.version,"created_at":row.created_at.isoformat(),"updated_at":row.updated_at.isoformat()}
def get_preset(s,actor,scope,key):
    if key.startswith("system:"):
        row=next((r for r in system_presets(scope) if r["id"]==key),None)
        if not row:raise HTTPException(404,"PRESET_NOT_FOUND")
        return row
    row=own(s,actor,key)
    if row.scope!=scope:raise HTTPException(422,"PRESET_SCOPE_MISMATCH")
    return preset_json(row)
def preference(s,actor,scope):
    return s.get(UserTablePreference,(actor["id"],actor["workspace"],scope))
def lock(s,actor,scope):
    if s.bind.dialect.name=="postgresql":
        s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"columns:"+actor["id"]+":"+actor["workspace"]+":"+scope})
def mutate_view(s,actor,scope,expected,**values):
    lock(s,actor,scope)
    row=preference(s,actor,scope)
    actual=row.version if row else 0
    if actual!=expected:raise HTTPException(409,"PREFERENCE_VERSION_CONFLICT")
    if row:
        result=s.execute(update(UserTablePreference).where(UserTablePreference.user_id==actor["id"],
            UserTablePreference.workspace_id==actor["workspace"],UserTablePreference.scope==scope,
            UserTablePreference.version==expected).values(**values,version=expected+1,updated_at=now()))
        if result.rowcount!=1:raise HTTPException(409,"PREFERENCE_VERSION_CONFLICT")
        s.expire(row)
    else:
        s.add(UserTablePreference(user_id=actor["id"],workspace_id=actor["workspace"],scope=scope,
            active_id=values.get("active_id","system:basic"),default_id=values.get("default_id","system:basic"),
            config_json=values.get("config_json",system_presets(scope)[0]["config"]),version=1,updated_at=now()))
    s.flush()
def bundle(s,actor,scope):
    custom=s.scalars(select(UserColumnPreset).where(UserColumnPreset.user_id==actor["id"],
        UserColumnPreset.workspace_id==actor["workspace"],UserColumnPreset.scope==scope).order_by(UserColumnPreset.created_at,UserColumnPreset.id)).all()
    systems=system_presets(scope);pref=preference(s,actor,scope)
    return {"scope":scope,"presets":systems+[preset_json(r) for r in custom],
        "preference":{"active_id":pref.active_id if pref else systems[0]["id"],
            "default_id":pref.default_id if pref else systems[0]["id"],
            "config":normalize_config(pref.config_json,scope) if pref else systems[0]["config"],
            "version":pref.version if pref else 0}}

@router.get(BASE+"/{scope}")
def read(scope:Scope,request:Request):
    actor=identity(request)
    with factory().begin() as s:
        lock(s,actor,scope)
        return bundle(s,actor,scope)
@router.post(BASE,status_code=201)
def create(command:Create,request:Request):
    actor=identity(request);cfg=config(command.config,command.scope);label=name(command.name)
    with factory().begin() as s:
        lock(s,actor,command.scope)
        row=UserColumnPreset(id=str(uuid4()),user_id=actor["id"],workspace_id=actor["workspace"],
            scope=command.scope,name=label,config_json=cfg,version=1,created_at=now(),updated_at=now())
        s.add(row);s.flush()
        mutate_view(s,actor,command.scope,command.preference_version,active_id=row.id,config_json=cfg)
        return bundle(s,actor,command.scope)
@router.put(BASE+"/presets/{key}")
def edit(key:str,command:Edit,request:Request):
    actor=identity(request)
    with factory().begin() as s:
        row=own(s,actor,key);lock(s,actor,row.scope)
        cfg=config(command.config,row.scope);label=name(command.name)
        result=s.execute(update(UserColumnPreset).where(UserColumnPreset.id==row.id,UserColumnPreset.version==command.version).values(name=label,
            config_json=cfg,version=command.version+1,updated_at=now()))
        if result.rowcount!=1:raise HTTPException(409,"PRESET_VERSION_CONFLICT")
        pref=preference(s,actor,row.scope)
        mutate_view(s,actor,row.scope,command.preference_version,**({"config_json":cfg} if pref and pref.active_id==row.id else {}))
        s.expire(row)
        return bundle(s,actor,row.scope)
@router.delete(BASE+"/presets/{key}")
def remove(key:str,request:Request,version:int=Query(ge=1),preference_version:int=Query(ge=0)):
    actor=identity(request)
    with factory().begin() as s:
        row=own(s,actor,key);scope=row.scope;lock(s,actor,scope)
        if row.version!=version:raise HTTPException(409,"PRESET_VERSION_CONFLICT")
        pref=preference(s,actor,scope);values={}
        if pref:
            default_id="system:basic" if pref.default_id==key else pref.default_id
            if pref.default_id==key:values["default_id"]=default_id
            if pref.active_id==key:values.update(active_id=default_id,config_json=get_preset(s,actor,scope,default_id)["config"])
        mutate_view(s,actor,scope,preference_version,**values)
        deleted=s.execute(delete(UserColumnPreset).where(UserColumnPreset.id==key,UserColumnPreset.version==version))
        if deleted.rowcount!=1:raise HTTPException(409,"PRESET_VERSION_CONFLICT")
        return bundle(s,actor,scope)
@router.put(BASE+"/{scope}/view")
def view(scope:Scope,command:View,request:Request):
    actor=identity(request);cfg=config(command.config,scope)
    with factory().begin() as s:
        lock(s,actor,scope)
        get_preset(s,actor,scope,command.active_id)
        mutate_view(s,actor,scope,command.version,active_id=command.active_id,config_json=cfg)
        return bundle(s,actor,scope)
@router.post(BASE+"/{scope}/activate")
def activate(scope:Scope,command:Choose,request:Request):
    actor=identity(request)
    with factory().begin() as s:
        lock(s,actor,scope)
        selected=get_preset(s,actor,scope,command.preset_id)
        mutate_view(s,actor,scope,command.version,active_id=selected["id"],config_json=selected["config"])
        return bundle(s,actor,scope)
@router.put(BASE+"/{scope}/default")
def default(scope:Scope,command:Choose,request:Request):
    actor=identity(request)
    with factory().begin() as s:
        lock(s,actor,scope)
        get_preset(s,actor,scope,command.preset_id)
        mutate_view(s,actor,scope,command.version,default_id=command.preset_id)
        return bundle(s,actor,scope)
