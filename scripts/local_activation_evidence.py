"""Local activation evidence; subprocess output and DB values never printed."""
import hashlib,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=str(Path.home()/'AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe')
P=[D,'compose','--project-directory',str(ROOT),'--env-file',str(ROOT/'.env'),'-f',str(ROOT/'docker-compose.yml'),'-p','metric-control-center','--profile','web']
def run(args,data=None):
 r=subprocess.run(args,input=data,capture_output=True)
 if r.returncode:raise RuntimeError('ACTIVATION_COMMAND_FAILED: '+args[-1][:80])
 return r.stdout
def sql(query,db='metric_control'):
 return run(P+['exec','-T','postgres','psql','-X','-A','-t','-v','ON_ERROR_STOP=1','-U','metric_control','-d',db],query.encode()).decode().strip()
def snapshot(db='metric_control'):
 tables=json.loads(sql("SELECT coalesce(json_agg(tablename ORDER BY tablename),'[]') FROM pg_tables WHERE schemaname='public';",db))
 result={}
 for t in tables:
  assert t.replace('_','').isalnum()
  rows=json.loads(sql('SELECT coalesce(json_agg(row_to_json(t)),\'[]\') FROM "'+t+'" t;',db))
  values=sorted(json.dumps(r,sort_keys=True,separators=(',',':'),ensure_ascii=True) for r in rows)
  result[t]={'count':len(rows),'sha256':hashlib.sha256('\n'.join(values).encode()).hexdigest()}
 return result
if __name__=='__main__':
 mode=sys.argv[1]
 state=ROOT/'.tools/activation-state.json'
 if mode=='backup':
  stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');folder=ROOT/'.tools'/('activation-'+stamp);folder.mkdir()
  for f in ('docker-compose.yml','docker-compose.production.yml'):(folder/f).write_bytes((ROOT/f).read_bytes())
  images={}
  for service in ('backend','frontend','worker','scheduler'):
   cid=run(P+['ps','-a','-q',service]).decode().strip();images[service]=run([D,'inspect','--format','{{.Image}}',cid]).decode().strip()
  (folder/'previous-images.json').write_text(json.dumps(images,indent=2))
  before=snapshot();revision=sql('SELECT version_num FROM alembic_version;')
  assert revision=='0008_column_preferences',revision
  (folder/'before.json').write_text(json.dumps(before,indent=2))
  last=sql("SELECT coalesce(json_agg(t),'[]') FROM (SELECT provider,max(finished_at) last_success FROM sync_runs WHERE status='succeeded' GROUP BY provider) t;")
  (folder/'last-successful-sync.json').write_text(last)
  backups=ROOT/'backups';backups.mkdir(exist_ok=True);dump=backups/('activation-'+stamp+'.dump')
  content=run(P+['exec','-T','postgres','pg_dump','-U','metric_control','-d','metric_control','--format=custom','--no-owner','--no-acl']);dump.write_bytes(content)
  digest=hashlib.sha256(content).hexdigest();dump.with_suffix('.sha256').write_text(digest+'\n')
  assert hashlib.sha256(dump.read_bytes()).hexdigest()==digest
  testdb='mcc_activation_restore_'+stamp.lower().replace('t','_').replace('z','')
  run(P+['exec','-T','postgres','createdb','-U','metric_control',testdb])
  run(P+['exec','-T','postgres','pg_restore','-U','metric_control','--exit-on-error','--no-owner','--no-acl','--dbname',testdb],content)
  restored=snapshot(testdb);assert restored==before,'RESTORE_DATA_MISMATCH'
  (folder/'restored.json').write_text(json.dumps(restored,indent=2))
  result={'folder':str(folder),'backup':str(dump),'sha256':digest,'bytes':len(content),'restore_database':testdb,'restore':'PASS','revision_before':revision,'protected_tables':len(before),'created_at':stamp}
  state.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
 elif mode=='compare':
  info=json.loads(state.read_text());folder=Path(info['folder']);before=json.loads((folder/'before.json').read_text());after=snapshot();(folder/'after-migration.json').write_text(json.dumps(after,indent=2))
  differences=[t for t in before if t!='alembic_version' and before[t]!=after.get(t)]
  assert not differences,'MIGRATION_DATA_MISMATCH: '+','.join(differences)
  assert sql('SELECT version_num FROM alembic_version;')=='0009_providers'
  added=sorted(set(after)-set(before));assert len(added)==8
  info.update(migration='PASS',data_integrity='PASS',added_tables=added);state.write_text(json.dumps(info,indent=2));print(json.dumps({'migration':'PASS','unchanged_existing_tables':len(before)-1,'added_tables':added},indent=2))
 else:raise RuntimeError('INVALID_MODE')
