"""Safe comparison of protected READ data, excluding transient sessions and UI preferences."""
import hashlib,json
from sqlalchemy import text
from services.storage.database import make_engine
engine=make_engine()
tables=["users","ad_accounts","entities","campaigns","adsets","ads","creatives","daily_metrics","tracker_metrics","breakdowns","entity_current_state","read_statistics","action_requests","action_executions","action_logs"]
out={}
with engine.connect() as c:
 for table in tables:
  rows=c.execute(text('SELECT * FROM "'+table+'"')).mappings().all()
  values=sorted(json.dumps(dict(r),sort_keys=True,default=str,ensure_ascii=True,separators=(",",":")) for r in rows)
  out[table]={"count":len(rows),"sha256":hashlib.sha256("\n".join(values).encode()).hexdigest()}
print(json.dumps(out,sort_keys=True))