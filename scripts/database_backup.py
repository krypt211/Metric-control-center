"""Atomic pg_dump backups; isolated pg_restore validation; explicit destructive restore."""
import argparse
from datetime import datetime,timezone,timedelta
import hashlib,json,os
from pathlib import Path
import re,subprocess,sys,time
def emit(event,level="INFO",**extra):
    print(json.dumps({"timestamp":datetime.now(timezone.utc).isoformat(),"service":"backup","level":level,
        "request_id":None,"event":event,"error_code":event if level=="ERROR" else None,**extra}),flush=True)
def env():
    value=dict(os.environ);value["PGPASSWORD"]=Path(value["POSTGRES_PASSWORD_FILE"]).read_text().strip()
    value["PGHOST"]=value.get("POSTGRES_HOST","postgres");value["PGUSER"]=value["POSTGRES_USER"]
    value["PGDATABASE"]=value["POSTGRES_DB"]
    return value
def run(args,e):
    p=subprocess.run(args,env=e,capture_output=True,text=True)
    if p.returncode:raise RuntimeError("DATABASE_COMMAND_FAILED")
    return p.stdout
def stats(e,database=None):
    args=["psql","-X","-A","-t","-v","ON_ERROR_STOP=1"]
    if database:args+=["-d",database]
    result={}
    for table in ["daily_metrics","ad_accounts","entities","users","user_sessions","read_statistics","sync_runs","action_requests","action_executions"]:
        sql="SELECT count(*), md5(coalesce(string_agg(md5(row_to_json(t)::text), '' ORDER BY row_to_json(t)::text), '')) FROM "+table+" t"
        row=run(args+["-c",sql],e).strip().split("|");result[table]={"rows":int(row[0]),"digest":row[1]}
    result["migration"]=run(args+["-c","SELECT version_num FROM alembic_version"],e).strip()
    return result
def validate_path(name):
    root=Path(os.environ.get("BACKUP_DIR","/backups")).resolve();path=(root/name).resolve()
    if path.parent!=root or not re.fullmatch(r"mcc-\d{8}T\d{6}Z-[a-f0-9]{8}\.dump",path.name):
        raise ValueError("INVALID_BACKUP_PATH")
    return path
def backup():
    e=env();root=Path(os.environ.get("BACKUP_DIR","/backups"));root.mkdir(parents=True,exist_ok=True)
    days=int(os.environ.get("BACKUP_RETENTION_DAYS","14"))
    if days<1:raise ValueError("INVALID_RETENTION")
    now=datetime.now(timezone.utc)
    path=validate_path("mcc-"+now.strftime("%Y%m%dT%H%M%SZ")+"-"+os.urandom(4).hex()+".dump")
    temp=path.with_suffix(".partial")
    p=subprocess.run(["pg_dump","--format=custom","--no-owner","--no-acl","--file",str(temp)],env=e,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if p.returncode:temp.unlink(missing_ok=True);raise RuntimeError("PG_DUMP_FAILED")
    temp.chmod(0o600);temp.replace(path)
    path.with_suffix(".sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest()+"\n");path.with_suffix(".sha256").chmod(0o600)
    cutoff=now-timedelta(days=days)
    for old in root.glob("mcc-*.dump"):
        old=validate_path(old.name)
        if datetime.fromtimestamp(old.stat().st_mtime,timezone.utc)<cutoff:
            old.unlink();old.with_suffix(".sha256").unlink(missing_ok=True)
    emit("backup_created",file=path.name,bytes=path.stat().st_size)
    return path
def verify_checksum(path):
    expected=path.with_suffix(".sha256").read_text().strip()
    if not re.fullmatch("[a-f0-9]{64}",expected) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise ValueError("BACKUP_CHECKSUM_MISMATCH")
def restore_test(path):
    e=env();verify_checksum(path);target="mcc_restore_test_"+os.urandom(6).hex()
    before=stats(e);run(["createdb",target],e)
    try:
        run(["pg_restore","--exit-on-error","--no-owner","--no-acl","--dbname",target,str(path)],e)
        after=stats(e,target)
        if before!=after:raise RuntimeError("RESTORE_DATA_MISMATCH")
        emit("restore_test_pass",isolated_database=target,table_count=len(after)-1)
        return {"status":"PASS","isolated":True,"tables":after}
    finally:run(["dropdb",target],e)
def restore(path,confirm):
    verify_checksum(path);e=env()
    if confirm!=e["POSTGRES_DB"]:raise ValueError("EXPLICIT_DATABASE_CONFIRMATION_REQUIRED")
    run(["pg_restore","--exit-on-error","--clean","--if-exists","--no-owner","--no-acl","--dbname",e["POSTGRES_DB"],str(path)],e)
    emit("restore_completed")
def main():
    p=argparse.ArgumentParser();p.add_argument("command",choices=["backup","job","restore-test","restore"])
    p.add_argument("--file");p.add_argument("--confirm-database");a=p.parse_args()
    try:
        if a.command=="backup":backup()
        elif a.command=="restore-test":
            path=validate_path(a.file) if a.file else backup();print(json.dumps(restore_test(path)))
        elif a.command=="restore":restore(validate_path(a.file),a.confirm_database)
        else:
            while True:
                try:backup()
                except Exception:emit("BACKUP_FAILED","ERROR")
                time.sleep(86400)
        return 0
    except Exception as error:
        code=str(error) if str(error) in ("PG_DUMP_FAILED","RESTORE_DATA_MISMATCH","BACKUP_CHECKSUM_MISMATCH","EXPLICIT_DATABASE_CONFIRMATION_REQUIRED","INVALID_BACKUP_PATH","INVALID_RETENTION") else "BACKUP_OPERATION_FAILED"
        emit(code,"ERROR");return 1
if __name__=="__main__":sys.exit(main())
