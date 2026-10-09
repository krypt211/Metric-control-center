"""Repeatable local HTTP/PostgreSQL UI-1 acceptance checks; no advertising commands."""
import argparse,copy,json,os,secrets,subprocess,time
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import httpx
ROOT=Path(__file__).resolve().parents[1]
DOCKER=Path(os.environ.get("LOCALAPPDATA",""))/"Programs/DockerDesktop/resources/bin/docker.exe"
if not DOCKER.exists():DOCKER=Path("docker")
PREFIX=[str(DOCKER),"compose","--project-directory",str(ROOT),"--env-file",str(ROOT/".env"),"-f",str(ROOT/"docker-compose.yml"),"-p","metric-control-center"]
SCOPES=["account","campaign","adset","ad","creative","tracker"]
def fixture(mode,nonce):
 source=(ROOT/"frontend/e2e/accounts.py").read_text(encoding="utf8")
 result=subprocess.run(PREFIX+["exec","-T","-e","UI_FIXTURE_MODE="+mode,"-e","UI_FIXTURE_NONCE="+nonce,"backend","python","-c","import sys;exec(sys.stdin.read())"],input=source,text=True,capture_output=True,encoding="utf8",check=True)
 return json.loads(result.stdout)
def mutate(c,method,path,body=None,expected=200):
 csrf=c.get("/api/auth/csrf");assert csrf.status_code==200,"CSRF unavailable"
 r=c.request(method,path,headers={"Origin":str(c.base_url).rstrip("/"),"X-CSRF-Token":csrf.json()["csrf_token"]},json=body)
 assert r.status_code==expected,"Unexpected HTTP status for "+method+" "+path+": "+str(r.status_code)
 return r.json() if r.content else {}
def login(c,u):
 mutate(c,"POST","/api/auth/login",{"login":u["login"],"password":u["password"]})
 assert c.get("/api/auth/me").status_code==200
def get(c,scope):
 r=c.get("/api/preferences/columns/"+scope);assert r.status_code==200
 return r.json()
def wait_ready(base):
 deadline=time.monotonic()+120
 while time.monotonic()<deadline:
  try:
   if httpx.get(base+"/api/auth/csrf",timeout=3).status_code==200 and httpx.get("http://127.0.0.1:8000/health/ready",timeout=3).status_code==200:return
  except httpx.HTTPError:pass
  time.sleep(1)
 raise RuntimeError("Restart readiness timeout")
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--restart",action="store_true");parser.add_argument("--output",default=".tools/ui-http-evidence.json");args=parser.parse_args()
 nonce=uuid4().hex;base="http://127.0.0.1:3000";evidence={"scope_checks":{},"browser":"NOT EXECUTED"}
 try:
  users=fixture("create",nonce)
  with httpx.Client(base_url=base,timeout=30) as c,httpx.Client(base_url=base,timeout=30) as other:
   assert c.get("/api/preferences/columns/account").status_code==401;evidence["authentication_required"]="PASS"
   login(c,users[0]);evidence["login"]="PASS"
   dashboard=c.get("/api/dashboard");assert dashboard.status_code==200;evidence["dashboard"]="PASS"
   capabilities=c.get("/api/capabilities");assert capabilities.status_code==200
   assert capabilities.json()["actions_enabled"] is False;evidence["actions_enabled"]=False
   snapshots={}
   for scope in SCOPES:
    b=get(c,scope);assert len([p for p in b["presets"] if p["system"]])==6
    cfg=copy.deepcopy(b["preference"]["config"]);cfg["columns"][0]["width"]=333
    if len(cfg["columns"])>2:cfg["columns"][1:]=list(reversed(cfg["columns"][1:]))
    b=mutate(c,"POST","/api/preferences/columns",{"scope":scope,"name":"UI-1 \u041c\u043e\u0439 "+scope,"config":cfg,"preference_version":b["preference"]["version"]},201)
    own=next(p for p in b["presets"] if p["id"]==b["preference"]["active_id"]);key=own["id"]
    b=mutate(c,"PUT","/api/preferences/columns/"+scope+"/default",{"preset_id":key,"version":b["preference"]["version"]})
    cfg["columns"][0]["width"]=377
    b=mutate(c,"PUT","/api/preferences/columns/"+scope+"/view",{"active_id":key,"config":cfg,"version":b["preference"]["version"]})
    assert next(p for p in b["presets"] if p["id"]==key)["config"]["columns"][0]["width"]==333
    assert b["preference"]["config"]["columns"][0]["width"]==377
    snapshots[scope]=b["preference"]
    evidence["scope_checks"][scope]="PASS"
   b=get(c,"account");key=b["preference"]["active_id"];p=next(p for p in b["presets"] if p["id"]==key)
   b=mutate(c,"PUT","/api/preferences/columns/presets/"+key,{"name":"UI-1 renamed","config":b["preference"]["config"],"version":p["version"],"preference_version":b["preference"]["version"]})
   snapshots["account"]=b["preference"]
   second=mutate(c,"POST","/api/preferences/columns",{"scope":"account","name":"UI-1 duplicate","config":b["preference"]["config"],"preference_version":b["preference"]["version"]},201)
   q=next(p for p in second["presets"] if p["id"]==second["preference"]["active_id"])
   b=mutate(c,"DELETE","/api/preferences/columns/presets/"+q["id"]+"?version="+str(q["version"])+"&preference_version="+str(second["preference"]["version"]))
   assert b["preference"]["active_id"]==key;evidence["multiple_rename_duplicate_default_delete"]="PASS";snapshots["account"]=b["preference"]
   login(other,users[1]);b=get(other,"account");assert len(b["presets"])==6
   mutate(other,"PUT","/api/preferences/columns/presets/"+key,{"name":"forged","config":b["preference"]["config"],"version":1,"preference_version":0},404)
   evidence["user_isolation"]="PASS"
   b=get(c,"ad");stale=copy.deepcopy(b["preference"])
   changed=copy.deepcopy(stale["config"]);changed["columns"][0]["width"]=388
   b=mutate(c,"PUT","/api/preferences/columns/ad/view",{"active_id":stale["active_id"],"config":changed,"version":stale["version"]})
   mutate(c,"PUT","/api/preferences/columns/ad/view",{"active_id":stale["active_id"],"config":stale["config"],"version":stale["version"]},409)
   snapshots["ad"]=b["preference"];evidence["version_conflict"]="PASS"
   token=c.get("/api/auth/csrf").json()["csrf_token"]
   def concurrent_write(width):
    cfg=copy.deepcopy(b["preference"]["config"]);cfg["columns"][0]["width"]=width
    return c.put("/api/preferences/columns/ad/view",headers={"Origin":base,"X-CSRF-Token":token},json={"active_id":b["preference"]["active_id"],"config":cfg,"version":b["preference"]["version"]})
   with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(concurrent_write,[399,411]))
   assert sorted(r.status_code for r in results)==[200,409],"Concurrent writers must not silently overwrite"
   snapshots["ad"]=get(c,"ad")["preference"];evidence["postgresql_concurrent_write_conflict"]="PASS"

   for scope in SCOPES:assert get(c,scope)["preference"]==snapshots[scope]
   evidence["refresh_http_persistence"]="PASS"
   mutate(c,"POST","/api/auth/logout");assert c.get("/api/preferences/columns/account").status_code==401;login(c,users[0])
   for scope in SCOPES:assert get(c,scope)["preference"]==snapshots[scope]
   evidence["logout_login_persistence"]="PASS"
   if args.restart:
    subprocess.run(PREFIX+["--profile","web","restart","backend","frontend"],check=True,capture_output=True)
    wait_ready(base)
    assert c.get("/api/auth/me").status_code==200
    for scope in SCOPES:assert get(c,scope)["preference"]==snapshots[scope]
    evidence["docker_restart_sessions_and_settings"]="PASS"
   else:evidence["docker_restart_sessions_and_settings"]="NOT EXECUTED"
   from datetime import datetime,timedelta
   from zoneinfo import ZoneInfo
   today=datetime.now(ZoneInfo("Europe/Moscow")).date()
   evidence["live_date_ranges"]={}
   for name,start,end in (("Today",today,today),("Yesterday",today-timedelta(days=1),today-timedelta(days=1)),("7d",today-timedelta(days=6),today),("30d",today-timedelta(days=29),today)):
    levels={}
    for level in ("account","campaign","adset","ad"):
     r=c.get("/api/stats/table",params={"start":str(start),"end":str(end),"level":level,"limit":500});assert r.status_code==200
     rows=r.json()["rows"];assert rows and len({row["id"] for row in rows})==len(rows)
     levels[level]=r.json()["total"]
    evidence["live_date_ranges"][name]=levels
   query={"start":"2020-01-01","end":"2030-12-31","level":"ad","sort_key":"spend","sort_direction":"desc","limit":500}
   full=c.get("/api/stats/table",params=query);assert full.status_code==200
   all_rows=full.json()["rows"];assert len(all_rows)>1,"Existing advertising facts required for live sorting check"
   query["limit"]=1
   a=c.get("/api/stats/table",params=query).json()
   query["offset"]=1;z=c.get("/api/stats/table",params=query).json()
   assert a["rows"][0]["id"]==all_rows[0]["id"] and z["rows"][0]["id"]==all_rows[1]["id"]
   assert a["total"]==full.json()["total"];evidence["full_filtered_server_sort_before_pagination"]="PASS"
   for kind in ["creative","tracker"]:
    r=c.get("/api/stats/optional",params={"start":"2020-01-01","end":"2030-12-31","kind":kind,"sort_key":"clicks","sort_direction":"desc","limit":1})
    assert r.status_code==200;evidence[kind+"_table_endpoint"]="PASS"
  evidence["status"]="PASS"
 finally:
  fixture("cleanup",nonce)
 output=ROOT/args.output;output.parent.mkdir(exist_ok=True,parents=True);output.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf8")
 print(json.dumps(evidence,indent=2))
if __name__=="__main__":main()