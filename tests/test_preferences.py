from pathlib import Path
from unittest.mock import patch
import os,unittest,copy,json
import httpx
from sqlalchemy import select
from backend.app import app
from services.auth.sessions import new_user
from services.preferences.registry import system_presets,normalize_config,sort_rows,registry
from services.storage.models import UserColumnPreset
from test_sync import StorageFixture,DAY,row
from test_auth import MemoryLimits

class PreferenceTests(StorageFixture,unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  super().setUp();secret=Path(self.directory.name)/"secret";secret.write_text("p"*48)
  self.env=patch.dict(os.environ,{"AUTH_ENABLED":"true","APP_ENV":"development","SESSION_SECRET_FILE":str(secret),"APP_ORIGIN":"http://test","WORKSPACE_ID":"default","LOCAL_READ_ONLY":"true","ACTIONS_ENABLED":"false","AUTH_TRUST_PROXY":"false"});self.env.start()
  self.patches=[patch("backend.app.database_sessions",return_value=self.sessions),patch("backend.auth.limiter",return_value=MemoryLimits())]
  for p in self.patches:p.start()
  with self.sessions.begin() as s:
   new_user(s,"default","a","private-fixture-password","viewer")
   new_user(s,"default","b","private-fixture-password","operator")
   new_user(s,"other","foreign","private-fixture-password","viewer")
  self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test")
 async def asyncTearDown(self):await self.client.aclose()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.env.stop();super().tearDown()
 async def headers(self):
  r=await self.client.get("/api/auth/csrf")
  return {"Origin":"http://test","X-CSRF-Token":r.json()["csrf_token"]}
 async def login(self,user="a"):
  return await self.client.post("/api/auth/login",headers=await self.headers(),json={"login":user,"password":"private-fixture-password"})
 async def bundle(self,scope="ad"):return (await self.client.get("/api/preferences/columns/"+scope)).json()
 async def create(self,scope="ad",label="My preset",cfg=None):
  b=await self.bundle(scope)
  return await self.client.post("/api/preferences/columns",headers=await self.headers(),json={"scope":scope,"name":label,"config":cfg or b["preference"]["config"],"preference_version":b["preference"]["version"]})
 async def test_authentication_csrf_and_read_only_exception_is_narrow(self):
  self.assertEqual((await self.client.get("/api/preferences/columns/ad")).status_code,401)
  await self.login()
  self.assertEqual((await self.client.post("/api/preferences/columns",json={})).status_code,403)
  self.assertEqual((await self.client.post("/api/actions",headers=await self.headers(),json={})).status_code,403)
  self.assertEqual((await self.create()).status_code,201)
 async def test_full_crud_multiple_presets_rename_default_delete(self):
  await self.login()
  first=(await self.create()).json();p=next(p for p in first["presets"] if not p["system"])
  b=(await self.create(label="Second preset")).json()
  self.assertEqual(len([p for p in b["presets"] if not p["system"]]),2)
  q=next(p for p in b["presets"] if p["id"]==b["preference"]["active_id"])
  r=await self.client.put("/api/preferences/columns/presets/"+q["id"],headers=await self.headers(),json={"name":"Renamed","config":q["config"],"version":q["version"],"preference_version":b["preference"]["version"]})
  self.assertEqual(r.status_code,200);b=r.json();q=next(p for p in b["presets"] if p["id"]==q["id"]);self.assertEqual(q["name"],"Renamed")
  r=await self.client.put("/api/preferences/columns/ad/default",headers=await self.headers(),json={"preset_id":q["id"],"version":b["preference"]["version"]});self.assertEqual(r.status_code,200);b=r.json()
  self.assertEqual(b["preference"]["default_id"],q["id"])
  r=await self.client.delete("/api/preferences/columns/presets/"+q["id"]+"?version="+str(q["version"])+"&preference_version="+str(b["preference"]["version"]),headers=await self.headers())
  self.assertEqual(r.status_code,200);b=r.json();self.assertEqual(b["preference"]["active_id"],"system:basic");self.assertEqual(b["preference"]["default_id"],"system:basic")
  self.assertTrue(any(x["id"]==p["id"] for x in b["presets"]))
 async def test_user_ownership_and_workspace_identity_cannot_be_forged(self):
  await self.login();b=(await self.create()).json();p=next(p for p in b["presets"] if not p["system"])
  await self.login("b");self.assertFalse(any(not p["system"] for p in (await self.bundle())["presets"]))
  r=await self.client.put("/api/preferences/columns/presets/"+p["id"],headers={**await self.headers(),"X-User-ID":"a","X-Workspace-ID":"other"},json={"name":"Hijack","config":p["config"],"version":1,"preference_version":0})
  self.assertEqual(r.status_code,404)
  self.assertEqual((await self.login("foreign")).status_code,401)
 async def test_config_width_scope_order_and_name_validation(self):
  await self.login()
  for field,value in [("key","fake_metric"),("width",79),("width",601),("width",True)]:
   cfg=copy.deepcopy(system_presets("ad")[0]["config"]);cfg["columns"][1][field]=value
   self.assertEqual((await self.create(cfg=cfg)).status_code,422)
  for kind in ["missing_name","duplicate","wrong_scope"]:
   cfg=copy.deepcopy(system_presets("ad")[0]["config"])
   if kind=="missing_name":cfg["columns"]=cfg["columns"][1:]
   elif kind=="duplicate":cfg["columns"].append(cfg["columns"][0])
   else:cfg["columns"].append({"key":"tracker_sales","width":140})
   self.assertEqual((await self.create(cfg=cfg)).status_code,422)
  for label in [" ","x"*81,"bad\nname"]:self.assertEqual((await self.create(label=label)).status_code,422)
  b=await self.bundle()
  r=await self.client.post("/api/preferences/columns",headers=await self.headers(),json={"scope":"ad","name":"Valid","config":b["preference"]["config"],"preference_version":0,"user_id":"forged"})
  self.assertEqual(r.status_code,422)
 async def test_optimistic_conflicts_do_not_overwrite_saved_config(self):
  await self.login();b=(await self.create()).json();p=next(p for p in b["presets"] if not p["system"])
  payload={"name":"First tab","config":p["config"],"version":1,"preference_version":b["preference"]["version"]}
  self.assertEqual((await self.client.put("/api/preferences/columns/presets/"+p["id"],headers=await self.headers(),json=payload)).status_code,200)
  payload["name"]="Stale tab"
  self.assertEqual((await self.client.put("/api/preferences/columns/presets/"+p["id"],headers=await self.headers(),json=payload)).status_code,409)
  self.assertEqual(next(p for p in (await self.bundle())["presets"] if not p["system"])["name"],"First tab")
 async def test_working_view_persists_across_login_scope_and_engine_restart(self):
  await self.login();b=await self.bundle();cfg=copy.deepcopy(b["preference"]["config"]);cfg["columns"][1]["width"]=222
  r=await self.client.put("/api/preferences/columns/ad/view",headers=await self.headers(),json={"active_id":"system:basic","config":cfg,"version":0})
  self.assertEqual(r.status_code,200);self.assertEqual((await self.bundle("account"))["preference"]["version"],0)
  await self.client.post("/api/auth/logout",headers=await self.headers());await self.login()
  self.assertEqual((await self.bundle())["preference"]["config"]["columns"][1]["width"],222)
  from services.storage.database import make_engine,sessions
  db=make_engine(self.db.url)
  try:
   with patch("backend.app.database_sessions",return_value=sessions(db)):
    self.assertEqual((await self.bundle())["preference"]["config"]["columns"][1]["width"],222)
  finally:db.dispose()
 async def test_system_presets_are_immutable_and_view_versions_conflict(self):
  await self.login();b=await self.bundle();cfg=b["preference"]["config"]
  self.assertEqual((await self.client.put("/api/preferences/columns/presets/system:basic",headers=await self.headers(),json={"name":"Changed","config":cfg,"version":1,"preference_version":0})).status_code,404)
  payload={"active_id":"system:basic","config":cfg,"version":0}
  self.assertEqual((await self.client.put("/api/preferences/columns/ad/view",headers=await self.headers(),json=payload)).status_code,200)
  self.assertEqual((await self.client.put("/api/preferences/columns/ad/view",headers=await self.headers(),json=payload)).status_code,409)
  self.assertEqual((await self.bundle())["presets"][0]["name"],registry()["systems"]["basic"]["name"])

 async def test_stale_delete_keeps_preset_and_current_view(self):
  await self.login();b=(await self.create()).json();p=next(p for p in b["presets"] if not p["system"])
  r=await self.client.put("/api/preferences/columns/presets/"+p["id"],headers=await self.headers(),json={"name":"Updated","config":p["config"],"version":1,"preference_version":b["preference"]["version"]})
  self.assertEqual(r.status_code,200);current=r.json()
  r=await self.client.delete("/api/preferences/columns/presets/"+p["id"]+"?version=1&preference_version="+str(current["preference"]["version"]),headers=await self.headers())
  self.assertEqual(r.status_code,409);self.assertEqual(await self.bundle(),current)

class RegistrySortingTests(unittest.TestCase):
 def test_numeric_sort_and_nulls_last_both_directions(self):
  rows=[{"id":"a","spend":"10"},{"id":"b","spend":"2"},{"id":"c","spend":None},{"id":"d","spend":"0"}]
  self.assertEqual([r["id"] for r in sort_rows(rows,"spend","asc","ad")],["d","b","a","c"])
  self.assertEqual([r["id"] for r in sort_rows(rows,"spend","desc","ad")],["a","b","d","c"])
  with self.assertRaises(ValueError):sort_rows(rows,"unknown","desc","ad")
 def test_string_percent_sort_and_ties(self):
  rows=[{"id":"a","name":"Z","ctr":"10"},{"id":"b","name":"a","ctr":"2"},{"id":"c","name":None,"ctr":None}]
  self.assertEqual(sort_rows(rows,"name","asc","ad")[0]["id"],"b")
  self.assertEqual(sort_rows(rows,"ctr","desc","ad")[-1]["id"],"c")
 def test_registry_upgrade_keeps_existing_columns_and_ignores_retired_keys(self):
  cfg=system_presets("ad")[0]["config"];before=copy.deepcopy(cfg)
  cfg["columns"].append({"key":"retired_metric","width":140})
  result=normalize_config(cfg,"ad");self.assertEqual(result,before)
  extra=copy.deepcopy(registry());extra["metrics"]["new_event"]={**extra["metrics"]["clicks"],"key":"new_event"}
  with patch("services.preferences.registry.registry",return_value=extra):self.assertEqual(normalize_config(before,"ad"),before)
 def test_utf8_registry_and_stats_sources_have_no_damaged_labels(self):
  root=Path(__file__).resolve().parents[1]
  for path in [root/"frontend/lib/metric-registry.json",root/"frontend/components/Statistics.tsx",root/"frontend/components/OptionalStatistics.tsx",root/"frontend/app/page.tsx"]:
   text=path.read_text(encoding="utf8");self.assertNotIn("???",text);self.assertNotIn("\ufffd",text)
  for key,m in registry()["metrics"].items():
   self.assertEqual(m["key"],key);self.assertTrue(m["label"]);self.assertTrue(m["description"])
