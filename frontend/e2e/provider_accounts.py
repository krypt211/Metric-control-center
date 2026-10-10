"""Disposable private test users only; called through local Docker stdin, never served."""
import json,os,re,secrets
from sqlalchemy import delete,select,text
from backend.app import database_sessions
from services.auth.sessions import new_user
from services.storage.models import User,UserSession,UserColumnPreset,UserTablePreference
nonce=os.environ["UI_FIXTURE_NONCE"]
if not re.fullmatch(r"[a-f0-9]{32}",nonce):raise RuntimeError("INVALID_FIXTURE_NONCE")
if os.environ.get("APP_ENV")=="production" or os.environ.get("LOCAL_READ_ONLY")!="true" or os.environ.get("ACTIONS_ENABLED")!="false":
 raise RuntimeError("LOCAL_READ_ONLY_TEST_ENVIRONMENT_REQUIRED")
workspace=os.environ.get("WORKSPACE_ID","default")
logins=["provider-ui-"+nonce+"-"+str(i)+"@local.test" for i in range(2)]
with database_sessions().begin() as s:
 if s.scalar(text("SELECT version_num FROM alembic_version")) not in ("0009_providers","0010_economics","0012_manual_actions"):raise RuntimeError("UI_MIGRATION_REQUIRED")
 if os.environ["UI_FIXTURE_MODE"]=="create":
  password=secrets.token_urlsafe(24);users=[]
  for login,role in zip(logins,["admin","viewer"]):
   u=new_user(s,workspace,login,password,role);s.flush();users.append({"id":u.id,"login":login,"password":password})
  print(json.dumps(users))
 elif os.environ["UI_FIXTURE_MODE"]=="cleanup":
  ids=list(s.scalars(select(User.id).where(User.workspace_id==workspace,User.email.in_(logins))))
  if ids:
   s.execute(delete(UserColumnPreset).where(UserColumnPreset.user_id.in_(ids)))
   s.execute(delete(UserTablePreference).where(UserTablePreference.user_id.in_(ids)))
   s.execute(delete(UserSession).where(UserSession.user_id.in_(ids)))
   s.execute(delete(User).where(User.id.in_(ids),User.workspace_id==workspace,User.email.in_(logins)))
  print(json.dumps({"removed_temporary_users":len(ids)}))
 else:raise RuntimeError("INVALID_FIXTURE_MODE")